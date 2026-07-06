from flask import Flask
from flask_cors import CORS
from config.config import Config
import asyncio
import logging
import threading
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from pyngrok import ngrok
import os

from cloud_platform.application.operator_api import register_operator_routes
from cloud_platform.application import client_http
from cloud_platform.telegram_bot.routes.webhook_routes import init_routes

# - Queue imports
import time
import queue
from cloud_platform.types.edge import PrioritizedItem, ServiceQueueItem

# ── DT Architecture imports ───────────────────────────────────────────
# These follow the same layered structure as the lecture:
#   Virtualization → Services → Digital Twin → Application (APIs)
from cloud_platform.virtualization.digital_replica.schema_registry import SchemaRegistry
from cloud_platform.services.database_service import DatabaseService
from cloud_platform.digital_twin.dt_factory import DTFactory
from cloud_platform.application.dt_api import register_dt_api_blueprints
from config.config_loader import ConfigLoader
from cloud_platform.services.data_ingestion import ingest_edge_results

logger = logging.getLogger(__name__)
import threading

class TelegramBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.application = None
        self._initialise_bot_application()
        self._setup_handlers()
        self._setup_ngrok()

    def _telegram_loop_exception_handler(self, loop, context):
        exception = context.get("exception")
        message = context.get("message")
        if exception is not None:
            logger.error(
                "Unhandled exception in Telegram event loop: %s",
                message,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        else:
            logger.error("Unhandled exception in Telegram event loop: %s", message)

    def _create_persistent_event_loop(self):
        loop = asyncio.new_event_loop()
        loop.set_exception_handler(self._telegram_loop_exception_handler)

        def _run_loop_forever(loop):
            asyncio.set_event_loop(loop)
            try:
                loop.run_forever()
            except Exception:
                logger.exception("Telegram background event loop crashed")
            finally:
                loop.close()

        loop_thread = threading.Thread(target=_run_loop_forever, args=(loop,), daemon=True)
        loop_thread.start()
        return loop, loop_thread
    
    def _initialise_bot_application(self):
        # Create a persistent event loop and run it in a background thread
        loop, loop_thread = self._create_persistent_event_loop()

        # Initialize bot application
        self.application = Application.builder().token(self.cfg.TELEGRAM_BOT_TOKEN).build()
        self.application.bot_data["loop"] = loop  # Store loop reference for webhook routes
        self.application.bot_data["loop_thread"] = loop_thread  # Store loop thread reference for webhook routes
    

    def _setup_handlers(self):
        # Importa i nuovi handler
        from cloud_platform.telegram_bot.handlers.bot_handlers import (
            start_handler, help_handler, status_handler, chatid_handler, unknown_text_handler
        )

        self.application.add_handler(CommandHandler("start", start_handler))
        self.application.add_handler(CommandHandler("help", help_handler))
        self.application.add_handler(CommandHandler("status", status_handler))
        self.application.add_handler(CommandHandler("chatid", chatid_handler))
        
        # Sostituisce l'echo_handler: risponde a qualsiasi testo che non sia un comando
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text_handler))
        
        asyncio.run_coroutine_threadsafe(self.application.initialize(), self.application.bot_data["loop"]).result()
        asyncio.run_coroutine_threadsafe(self.application.start(), self.application.bot_data["loop"]).result()

    def _setup_ngrok(self):
        ngrok.set_auth_token(self.cfg.NGROK_AUTH_TOKEN)
        public_url = ngrok.connect(self.cfg.FLASK_PORT).public_url
        webhook_url = f"{public_url}{self.cfg.WEBHOOK_PATH}"
        print(f"Webhook URL: {webhook_url}")
        asyncio.run_coroutine_threadsafe(self.application.bot.set_webhook(webhook_url), self.application.bot_data["loop"]).result()

class FlaskServer:
    """
    This class encapsulates the Flask app and its setup. 
    It creates:
    - the Flask app and configures it to handle HTTP requests from researchers and operators
    - the Digital Twin architecture components (SchemaRegistry, DatabaseService, DTFactory)
      following the lecture's layered pattern
    """
    def __init__(self, cfg: Config, telegram_application=None):
        self.cfg = cfg
        self.app = Flask(__name__, template_folder=cfg.TEMPLATES_DIR, static_folder=cfg.STATIC_DIR)
        CORS(self.app)  # Enable CORS for all routes

        # Initialise the DT architecture components (mirrors the lecture's FlaskServer._init_components)
        self._init_dt_components()

        self._register_blueprints(telegram_application)

    def _init_dt_components(self):
        """
        Initialise the full Digital Twin stack and store references in app.config.

        This follows the exact same startup sequence as the lecture's FlaskServer:
            1. Create a SchemaRegistry and load YAML templates for each DR type.
            2. Load database config from YAML and connect a DatabaseService.
            3. Create a DTFactory that ties DB + schemas together.
            4. Store all three in app.config so Blueprints can access them via
               current_app.config['DT_FACTORY'], etc.
        """
        # ── 1. Schema Registry ────────────────────────────────────────
        # The registry is the single source of truth for DR structure.
        # Adding a new DR type only requires a new YAML + one load_schema() call here.
        schema_registry = SchemaRegistry()
        schema_registry.load_schema("gateway", "cloud_platform/virtualization/templates/gateway.yaml")
        schema_registry.load_schema("sensor", "cloud_platform/virtualization/templates/sensor.yaml")
        schema_registry.load_schema("actuator", "cloud_platform/virtualization/templates/actuator.yaml")
        schema_registry.load_schema("digital_twin", "cloud_platform/virtualization/templates/digital_twin.yaml")



        # ── 2. Database Service ───────────────────────────────────────
        # Load MongoDB connection details from config/database.yaml
        db_config = ConfigLoader.load_database_config()
        connection_string = ConfigLoader.build_connection_string(db_config)

        db_service = DatabaseService(
            connection_string=connection_string,
            db_name=db_config["settings"]["name"],
            schema_registry=schema_registry,
        )
        db_service.connect()

        # ── 3. DT Factory ────────────────────────────────────────────
        # The factory manages the lifecycle of DT documents in MongoDB and
        # can reconstitute live DigitalTwin objects on demand.
        dt_factory = DTFactory(
            name="etna", 
            db_service=db_service, 
            schema_registry=schema_registry,#C:\Users\giovanni\Desktop\IoT_Project\IoT_project\app.py
            dt_schema_path=os.path.join(
                os.getcwd(),
                "cloud_platform", 
                "virtualization", 
                "templates", 
                "digital_twin.yaml")
                )
        # dt_factory.create_dt() # create the DT entry if it doesn't exist

        # ── 4. Create the shared thread-safe queue
        ingestion_queue = queue.Queue()

        # ── 5. Create the service queue
        service_queue = queue.Queue()

        # ── 6. Store in app.config for Blueprint access ──────────────
        self.app.config["SCHEMA_REGISTRY"] = schema_registry
        self.app.config["DB_SERVICE"] = db_service
        self.app.config["DT_FACTORY"] = dt_factory
        self.app.config["INGESTION_QUEUE"] = ingestion_queue # it is a thread-safe queue for ingestion tasks, accessible by all Blueprints (useful for the operator API to enqueue ingestion tasks for the GatewayPoller)
        self.app.config["SERVICE_QUEUE"] = service_queue # it is a thread-safe queue for service tasks, accessible by all Blueprints

    def _register_blueprints(self, telegram_application=None):
        # Existing routes
        register_operator_routes(self.app)
        if telegram_application is not None:
            init_routes(self.app, telegram_application)
        else:
            logger.warning("Telegram bot not initialized; webhook routes not registered.")

        # DT Architecture API routes (DT CRUD, DR CRUD, service management)
        register_dt_api_blueprints(self.app)

    def run(self, host: str, port: int, debug: bool, application: Application = None):
        """Start the Flask server."""
        try: 
            print(f"Starting Flask server on {host}:{port} with debug={debug}")
            self.app.run(host=host, port=port, debug=debug, threaded = True)
        except Exception as e:
            print(f"Error starting Flask server: {e}")
        finally:
            # Clean up DT database connection on shutdown
            if "DB_SERVICE" in self.app.config:
                self.app.config["DB_SERVICE"].disconnect()
            if application and "loop" in application.bot_data:
                loop = application.bot_data["loop"]
                try:
                    asyncio.run_coroutine_threadsafe(application.stop(), loop).result(timeout=10)
                    asyncio.run_coroutine_threadsafe(application.shutdown(), loop).result(timeout=10)
                except Exception as e:
                    print(f"Error shutting down Telegram bot application: {e}")
                finally:
                    loop.call_soon_threadsafe(loop.stop)
                    loop_thread = application.bot_data.get("loop_thread")
                    if loop_thread:
                        loop_thread.join()

class IngestionWorker:
    '''
    This class encapsulates the ingestion worker that runs in a separate thread.
    It continuously listens to the ingestion queue for new edge results and processes them. 
    Finally, it puts the digested data into the service_queue for the services to consume.
    
    The item in the queue is expected to be a PrioritizedItem with the following structure:
    PrioritizedItem(
        priority=1, 
        item={
            "edge_results": EdgeResults,
            "command_id": str | None,
            "operator_id": str | None,
        }
    )
    '''
    def __init__(self, db_service, dt_factory, ingestion_queue: queue.PriorityQueue, service_queue: queue.Queue):
        self.db_service = db_service
        self.dt_factory = dt_factory
        self.queue = ingestion_queue
        self.service_queue = service_queue
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        # Push a dummy item with the highest priority (0) to unblock and kill the thread
        self.queue.put(PrioritizedItem(priority=0, item="STOP"))
        self._thread.join(timeout=5)

    def _run(self):
        logger.info("Ingestion Worker started.")
        while not self._stop_event.is_set():
            try:
                # This blocks until an item arrives!
                task = self.queue.get() # get the next item from the queue

                if task is None:
                    continue

                if task.item == "STOP":
                    self._stop_event.set()
                    self.queue.task_done()
                    break
                
                dt_data = ingest_edge_results(
                    self.db_service, 
                    task.item.get("edge_results"), 
                    self.dt_factory, 
                    submitter=task.item.get("operator_id"), 
                    command=task.item.get("command_id")
                )
                
                self.queue.task_done()

                self.service_queue.put(ServiceQueueItem(command_id="RUN SERVICE", dt_data=dt_data))
            except Exception as exc:
                logger.exception("Ingestion failed: %s", exc)

class GatewayPoller:
    def __init__(self, poll_interval_s: int, ingestion_queue: queue.Queue):
        self.poll_interval_s = poll_interval_s
        self.ingestion_queue = ingestion_queue
        self._stop_event = threading.Event()
        self._exception = None
        self._thread = threading.Thread(target=self._run_thread, daemon=True)

    def _run_thread(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._exception = exc
            logger.exception("Unhandled exception in GatewayPoller thread")
        finally:
            self._stop_event.set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        logger.info("Gateway poller started (interval=%.2fs)", self.poll_interval_s)
        while not self._stop_event.is_set():
            try:
                results = client_http.poll_gateways()
                # logger.info("\n\nGateway polling results: %s\n\n", results)
                if results:
                    self.ingestion_queue.put(PrioritizedItem(priority=2, 
                                                             item={ "edge_results": results,
                                                                   "command_id": None,
                                                                   "operator_id": None })) # IngestionWorker will handle the ingestion of the results

            except Exception as exc:
                logger.exception("Gateway polling failed: %s", exc)

            self._stop_event.wait(self.poll_interval_s)

class ServiceWorker:
    """
    This class encapsulates the service worker that runs in a separate thread.
    It continuously listens to the service queue for new tasks and processes them.
    """
    def __init__(self, service_queue: queue.Queue, dt_factory=None):
        self.service_queue = service_queue
        self.dt_factory = dt_factory
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        # Push a dummy item to unblock and kill the thread
        self.service_queue.put(ServiceQueueItem(command_id="STOP", dt_data=[]))
        self._thread.join(timeout=5)

    def _run(self):
        logger.info("Service Worker started.")
        while not self._stop_event.is_set():
            try:
                task = self.service_queue.get()  # get the next item from the queue

                if task is None:
                    continue

                if task.command_id == "STOP":
                    self._stop_event.set()
                    self.service_queue.task_done()
                    break

                # Process the service task
                self.process_service_task(task)

                # Used by Queue consumer threads. For each get() used to fetch a task,
                # a subsequent call to task_done() tells the queue that the processing
                # on the task is complete.
                self.service_queue.task_done()
            except Exception as exc:
                logger.exception("Service processing failed: %s", exc)

    def process_service_task(self, task):
        """
        Implement the logic to process the service task.
        
        Args:
            task (ServiceQueueItem): The service task to process.
                dt_data : 
                    common structure for all devices, regardless of type:{
                        "_id_document": dr_entry["_id"],
                        "dr_type": dr_type,
                        "device_id": device_id,
                        "device_type": device_type,
                    }

                    sensor-specific structure (only if dr_type == "sensor"): {
                        "current_value": 25.0 °C,  # current reading of the sensor
                        "threshold": 32.0 °C,      # threshold value for alerting
                        "alert_level": str,        # "critical" or "info"
                    }

                command_id: str | None,  # command_id of the command that generated this result
        """
        ### Get the list of services / instantieted objects from DT manifest and execute them 
        dt_services = self.dt_factory.get_services()
        for service in dt_services:
            try:
                result = service.execute(task.dt_data)
                logger.info("Service executed successfully with result: %s", result)
            except Exception as exc:
                logger.exception("Service %s execution failed: %s", service.__class__.__name__, exc)

        

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger().setLevel(logging.INFO)
    cfg = Config()

    telegram_bot = None
    if cfg.TELEGRAM_BOT_TOKEN:
        telegram_bot = TelegramBot(cfg)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN missing; skipping Telegram bot startup.")

    # Start the Flask server and initialize the database, DT factory, and ingestion queue
    server = FlaskServer(
        cfg,
        telegram_application=telegram_bot.application if telegram_bot else None,
    )
    if not server.app.config.get("DB_SERVICE"):
        raise RuntimeError("DB_SERVICE not initialized on Flask app")
    if not server.app.config.get("DT_FACTORY"):
        raise RuntimeError("DT_FACTORY not initialized on Flask app")
    if not server.app.config.get("INGESTION_QUEUE"):
        raise RuntimeError("INGESTION_QUEUE not initialized on Flask app")
    
    ingestion_worker = IngestionWorker(
        db_service=server.app.config.get("DB_SERVICE"),
        dt_factory=server.app.config.get("DT_FACTORY"),
        ingestion_queue=server.app.config.get("INGESTION_QUEUE"),
        service_queue=server.app.config.get("SERVICE_QUEUE")
    )
    ingestion_worker.start()
    
    poller = GatewayPoller(
        poll_interval_s = cfg.POLLING_INTERVAL_S, 
        ingestion_queue = server.app.config.get("INGESTION_QUEUE")
    )
    poller.start()

    service_worker = ServiceWorker(
        service_queue = server.app.config.get("SERVICE_QUEUE"),
        dt_factory = server.app.config.get("DT_FACTORY")
    )
    service_worker.start()

    try:
        server.run(
            host=cfg.FLASK_HOST,
            port=cfg.FLASK_PORT,
            debug=False,
            application=telegram_bot.application if telegram_bot else None,
        )
    finally:
        logger.info("\n\nShutting down workers...")
        poller.stop()
        ingestion_worker.stop()
        service_worker.stop()