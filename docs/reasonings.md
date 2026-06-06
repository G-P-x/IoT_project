## Steps
1. nel client_http distinguere tra attuatore e sensore perché il campo threshold è presente solo per i sensori
1. Creazione del documento Digital Twin per MongoDB
2. ricevere da gateway la soglia su cui il sensore rileva allarme
3. se valore superiore alla soglia manda a tutti l'allarme (attuatori gateways, operatori, hickers)
