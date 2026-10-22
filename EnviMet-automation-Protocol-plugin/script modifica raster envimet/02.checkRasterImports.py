from qgis.core import QgsProject

def debug_e_verifica_microclima():
    NOME_GRUPPO = "Risultati Allineati (EnvyMap)"
    TARGET_COUNT = 25
    
    localita = [
        "centro_storico_1", "centro_storico_2", "centro_storico_3", "centro_storico_4",
        "fronte_mare_1", "fronte_mare_2", "fronte_mare_3", "fronte_mare_4",
        "suburbano_1", "suburbano_2", "suburbano_3", "suburbano_4"
    ]
    altezze = ["0.0m-3.0m", "3.0m-6.0m", "6.0m-9.0m", "9.0m-12.0m", "12.0m-15.0m"]
    
    root = QgsProject.instance().layerTreeRoot()
    gruppo = root.findGroup(NOME_GRUPPO)
    
    if not gruppo:
        print(f"ERRORE CRITICO: Il gruppo '{NOME_GRUPPO}' non esiste in questo progetto.")
        return

    # Estrazione ignorando il vincolo del nodeType per sicurezza diagnostica
    nomi_layer = [child.name() for child in gruppo.children()]
    
    print("=" * 60)
    print(f"DIAGNOSTICA DI LIVELLO 1")
    print(f"Layer totali rilevati nel gruppo: {len(nomi_layer)}")
    if nomi_layer:
        print("Primi 5 layer campionati nel gruppo per controllo sintassi:")
        for n in nomi_layer[:5]:
            print(f"  -> '{n}'")
    print("=" * 60)

    if not nomi_layer:
        print("Sospendere analisi: Il gruppo è vuoto o non accessibile tramite l'API TreeRoot.")
        return

    # Matrice di accoppiamento stringhe pura (Case-Insensitive, senza regex rigide)
    for loc in localita:
        print(f"\nLocalità: {loc.upper()}")
        print("-" * 40)
        
        for alt in altezze:
            conteggio = 0
            for nome in nomi_layer:
                nome_lower = nome.lower()
                # Verifica l'inclusione esatta dei due token fondamentali
                if loc.lower() in nome_lower and alt.lower() in nome_lower:
                    # Controllo stringa per evitare il falso positivo di 'centro_storico_1' in 'centro_storico_11'/'21'
                    # Se cerchiamo 'centro_storico_1', verifichiamo che il carattere successivo non sia un numero
                    idx = nome_lower.find(loc.lower())
                    char_successivo = nome_lower[idx + len(loc):idx + len(loc) + 1]
                    if char_successivo.isdigit():
                        continue
                    conteggio += 1
            
            if conteggio == TARGET_COUNT:
                print(f"  [+] Altezza {alt}: OK ({conteggio}/{TARGET_COUNT})")
            else:
                print(f"  [!] Altezza {alt}: ANOMALIA - Rilevati: {conteggio}")

debug_e_verifica_microclima()