"""
Hurst Cycles & Giuseppe Migliorino Battleplan Service
Analisi ciclica quantitativa basata sulle teorie di J.M. Hurst e Giuseppe Migliorino:
- Principi di Armonicità, Sincronicità e Proporzionalità di Hurst
- Modello Ciclico Nominale (Ciclo T, T+1, T+2, T+3 Intermedio)
- Struttura del Battleplan a 4 Tempi di Migliorino
- Vincoli Ciclici Ribassisti/Rialzisti sui Sottocicli
- Future Line of Demarcation (FLD) di Hurst
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional

class HurstMigliorinoCycleService:
    @staticmethod
    def calculate_cycle_metrics(df: pd.DataFrame) -> Dict[str, Any]:
        """
        Calcola la centratura ciclica, il conteggio barre e i vincoli secondo Hurst e Migliorino.
        """
        data = df.dropna(subset=["Close"]).copy()
        if data.empty or len(data) < 65:
            return {}

        prices = data["Close"].values
        n_bars = len(prices)

        # 1. Ricerca del Minimo del Ciclo Intermedio (T+3 ~64-72 barre di borsa aperta)
        # Cerchiamo il minimo significativo nelle ultime 70 barre
        window_intermedio = 70
        recent_window = prices[-window_intermedio:]
        min_idx_relative = np.argmin(recent_window)
        bars_since_intermedio_min = window_intermedio - 1 - min_idx_relative
        min_intermedio_price = recent_window[min_idx_relative]

        # 2. Ciclo Mensile (T+2 ~28-34 barre)
        window_mensile = 32
        recent_mensile = prices[-window_mensile:]
        min_mensile_rel = np.argmin(recent_mensile)
        bars_since_mensile_min = window_mensile - 1 - min_mensile_rel
        min_mensile_price = recent_mensile[min_mensile_rel]

        # 3. Ciclo Settimanale (Tracy / T ~6-8 barre)
        window_settimanale = 8
        recent_settimanale = prices[-window_settimanale:]
        min_settimanale_rel = np.argmin(recent_settimanale)
        bars_since_settimanale_min = window_settimanale - 1 - min_settimanale_rel

        curr_price = float(prices[-1])

        # 4. Calcolo Vincolo Ciclico di Migliorino:
        # Se il prezzo attuale buca il minimo di partenza del ciclo in corso, scatta il VINCOLO RIBASSISTA
        vincolo_mensile = "LIBERO (Fase Rialzista o Indeterminata)"
        if curr_price < min_intermedio_price:
            vincolo_mensile = "⚠️ VINCOLO RIBASSISTA ATTIVO SU INTERMEDIO T+3: Il prezzo ha rotto il minimo di partenza del ciclo. Tutti i successivi sottocicli (T+1 e T) hanno vincolo a chiudere sotto i rispettivi massimi."
        elif bars_since_mensile_min > 16 and curr_price < min_mensile_price:
            vincolo_mensile = "🔴 VINCOLO RIBASSISTA SU CICLO MENSILE T+2: Chiusura della seconda metà del ciclo mensile in correzione verso il minimo."

        # 5. Hurst Future Line of Demarcation (FLD) per Ciclo a 20 barre (T+1)
        # FLD a periodo 20: trasla il prezzo indietro di 10 barre (metà periodo)
        fld_period = 20
        half_fld = fld_period // 2
        fld_val = float(prices[-half_fld]) if len(prices) >= half_fld else curr_price
        fld_signal = "Prezzo SOPRA la FLD di Hurst (Proiezione rialzista attiva)" if curr_price > fld_val else "Prezzo SOTTO la FLD di Hurst (Proiezione ribassista verso il minimo ciclico)"

        # 6. Posizionamento nel Battleplan a 4 Tempi di Giuseppe Migliorino (Ciclo Mensile T+2 da ~32 sedute)
        # Ogni tempo dura circa 8 sedute (un ciclo settimanale Tracy / T)
        durata_mensile_target = 32
        candele_al_minimo = max(0, durata_mensile_target - int(bars_since_mensile_min))

        if bars_since_mensile_min <= 8:
            quarto = 1
            fase_battleplan = "1° Quarto (Spinta Iniziale): Il ciclo è appena nato. Si è nella fase rialzista di accumulazione con forza propulsiva."
            consiglio_pratico = "Fase propizia per posizioni long: i minimi sono alle spalle."
        elif bars_since_mensile_min <= 16:
            quarto = 2
            fase_battleplan = "2° Quarto (Ricerca del Massimo): Si cerca il top del ciclo mensile prima del primo ritracciamento fisiologico."
            consiglio_pratico = "Attenzione a comprare sui massimi: siamo vicini al picco della sinusoide ciclica."
        elif bars_since_mensile_min <= 24:
            quarto = 3
            fase_battleplan = "3° Quarto (Indebolimento & Svolta Bearish): Il ciclo perde quota ed entra nella seconda metà, tendenzialmente discendente."
            consiglio_pratico = "Fase delicata: evitare acquisti anticipati, il trend ciclico è al ribasso."
        else:
            quarto = 4
            fase_battleplan = "4° Quarto (Chiusura del Ciclo): I prezzi stanno cercando il pavimento finale dove il ciclo morirà per far nascere quello successivo."
            consiglio_pratico = f"Mancano solo ~{candele_al_minimo} sedute alla fine del ciclo: prepara la liquidità per cogliere l'inversione sui minimi!"

        # Spiegazione semplice del vincolo
        if "⚠️ VINCOLO RIBASSISTA ATTIVO SU INTERMEDIO" in vincolo_mensile:
            spiegazione_vincolo = "Il titolo ha rotto il supporto di partenza: la legge dei cicli di Migliorino impone che i rimbalzi siano solo temporanei e che si scenda sotto i minimi precedenti prima di ripartire."
        elif "🔴 VINCOLO RIBASSISTA" in vincolo_mensile:
            spiegazione_vincolo = "Ciclo mensile debole: la seconda parte del mese deve necessariamente chiudere in ribasso."
        else:
            spiegazione_vincolo = "Nessun vincolo ribassista forzato: il ciclo è sano e i ritracciamenti sono normali opportunità d'acquisto."

        # Spiegazione semplice FLD di Hurst
        if curr_price > fld_val:
            spiegazione_fld = f"Il prezzo attuale ({curr_price:.2f} €) è SOPRA la linea spartiacque FLD ({fld_val:.2f} €): la forza ciclica è positiva."
        else:
            spiegazione_fld = f"Il prezzo attuale ({curr_price:.2f} €) è SOTTO la linea spartiacque FLD ({fld_val:.2f} €): proiezione ribassista verso il completamento della chiusura."

        return {
            "current_price": round(curr_price, 2),
            "bars_since_intermedio_min": int(bars_since_intermedio_min),
            "bars_since_mensile_min": int(bars_since_mensile_min),
            "bars_since_settimanale_min": int(bars_since_settimanale_min),
            "candele_al_minimo": candele_al_minimo,
            "tempo_battleplan": f"{quarto}° Tempo su 4 (Barra {bars_since_mensile_min} di ~32)",
            "descrizione_battleplan": fase_battleplan,
            "consiglio_pratico": consiglio_pratico,
            "vincolo_migliorino": vincolo_mensile,
            "spiegazione_vincolo": spiegazione_vincolo,
            "hurst_fld_value": round(fld_val, 2),
            "hurst_fld_signal": spiegazione_fld
        }
