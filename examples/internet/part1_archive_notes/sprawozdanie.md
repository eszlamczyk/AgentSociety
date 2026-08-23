# Sprawozdanie z badan - ewaluacja lokalnych modeli LLM w symulacji AgentSociety

## 1. Kontekst

Praca stanowi kontynuacje istniejacego projektu badawczego opartego na frameworku AgentSociety - systemie wieloagentowej symulacji spoleczenstwa z modulem korzystania z internetu. Modul ten modeluje agentow posiadajacych urzadzenia ICT (smartfon, laptop, desktop), lacznosc sieciowa (WiFi domowe, siec antenowa) oraz generujacych realistyczny ruch internetowy (przeglad, zakupy, praca, social media, streaming).

Celem niniejszej pracy bylo zbadanie mozliwosci uruchomienia symulacji z wykorzystaniem lokalnych modeli jezykowych dostepnych przez infrastrukture Cyfronetu (PLGrid), w szczegolosci polskiego modelu Bielik, oraz przeprowadzenie analizy ilosciowej i jakosciowej uzyskanych danych.

## 2. Przystosowanie do infrastruktury PLGrid

Uruchomienie frameworku na PLGrid wymagalo szeregu poprawek kompatybilnosci:

- Aktualizacja biblioteki AgentSociety pod katy zmian API (m.in. zastapienie usunieta metody `QdrantClient.search` na `query_points` w vectorstore)
- Poprawka modulu LLM pod katy PLGrid API (kompatybilnosc z vLLM)

Istotne ograniczenie: nie wszystkie modele dostepne na PLGrid obsluguja function calling wymagany przez AgentSociety (mechanizm wyboru bloku zachowania agenta). Konieczne jest uzycie modeli z skonfigurowanym `--tool-call-parser` po stronie serwera vLLM. W praktyce przykładowym poprawnie dzialajacym modelem okazal sie speakleash/Bielik-11B-v3.0-Instruct.

## 3. Infrastruktura metryk i analizy

Stworzono kompletny system zbierania i wizualizacji danych symulacji:

**Metryki wydajnosciowe** 
- zbieranie tokenow (input/output) i czasu wykonania per krok i per agent
- porownanie wydajnosci miedzy runami o roznej skali agentow

**Analiza aktywnosci internetowej** 
- rozklad typow aktywnosci per godzina symulowanego dnia
- liczba unikalnych adresow IP per agent (WiFi domowe vs siec antenowa)
- najczesciej odwiedzane strony per kategoria ruchu
- analiza slow kluczowych w opisach akcji agentow

**Analiza mobilnosci**
- trajektorie agentow w przestrzeni 2D
- rozklad odleglosci podrozy
- liczba podrozy per godzina vs IRL rush hours
- rozklad mobilnych vs stacjonarnych agentow

## 4. Eksperymenty

### 4.1 Testy skalowania

Przeprowadzono serie krotkich runow (1h symulowanego czasu) przy roznej liczbie agentow w celu zbadania charakterystyki wydajnosciowej na PLGrid:

| Konfiguracja | Agenci |
|---|---|
| 1 agent | 1 |
| 10 agentow, 1h | 10 |
| 10 agentow, 10h | 10 |
| 100 agentow, 1h | 100 |
| 1000 agentow (test przepustowości) | 1000 |
| 2000 agentow (test przepustowosci) | 2000 |

Wyniki: czas wykonania rosnie sublinearnie wzgledem liczby agentow, co wskazuje na efektywne rownolegle przetwarzanie. Rzeczywisty throughput PLGrid wynosi okolo 6000 tokenow/s i stanowi glowny sufit wydajnosciowy niezaleznie od liczby agentow.

### 4.2 Pelny dzien symulacji - 100 agentow

Glowny eksperyment jakosciowy: 100 agentow przez 24h symulowanego czasu (poniedzialek, start o 6:00), model Bielik-11B.

**Aktywnosc internetowa (3341 akcji):**
- Dominuje typ `browse` (45.8%), nastepnie `shop` (18.4%), `social` (12.5%), `work` (12.3%), `stream` (9.7%), `call` (1.2%)
- Smartfon jest dominujacym urzadzeniem (79% akcji)
- Najczesciej odwiedzane strony: biedronka.pl, kwestiasmaku.com, netto.pl - wskazuje na realistyczne zachowania zakupowe i kulinarne

**Mobilnosc przestrzenna:**
- 28 z 100 agentow wykonalo przynajmniej jeden ruch fizyczny (138 zdarzen lacznie)
- Ruchy koncentruja sie w godzinach porannych (6-9h), zgodnie z IRL wzorcem dojazdu do pracy
- Dominujacy cel ruchu: praca
- Odleglosci podrozy: min 20m, max 5200m, srednia 1769m

**Adresy IP:**
- Agenci otrzymuja IP z sieci domowej (172.16.x.x) lub antenowej (10.0.x.x) w zaleznosci od lokalizacji
- Liczba unikalnych IP per agent odzwierciedla aktywnosc ruchowa

### 4.3 Porownanie modeli

Przeprowadzono run 100 agentow / 24h z modelem Qwen3-Coder-30B-A3B-Instruct (Qwen3-30B). Roznice w zachowaniu agentow sa znaczace.

**Rozklad typow aktywnosci internetowej:**

| Typ | Bielik-11B | Qwen3-30B |
|---|---|---|
| browse | 45.9% | 15.1% |
| shop | 18.4% | 2.2% |
| social | 12.5% | **52.9%** |
| work | 12.3% | 13.9% |
| stream | 9.7% | 1.5% |
| call | 1.2% | **14.4%** |
| Lacznie akcji | 3341 | 5376 |

**Mobilnosc przestrzenna:**

| | Bielik-11B | Qwen3-30B |
|---|---|---|
| Agenci poruszajacy sie | 28 / 100 | 12 / 100 |
| Zdarzenia ruchowe | 138 | 72 |

**Obserwacje:**

Qwen3-30B generuje znaczaco wiecej akcji ogolnie (5376 vs 3341), jednak jest silnie ukierunkowany na aktywnosc spolecznosciowa - `social` i `call` lacznie stanowia az 67.3% wszystkich akcji, podczas gdy w Bieliku bylo to 13.7%. Top 5 odwiedzanych stron to wylacznie platformy social media (facebook.com, instagram.com, x.com, messenger.com, snapchat.com), wobec stron zakupowych i kulinarnych w Bieliku.

Jednoczesnie Qwen3-30B generuje znacznie mniej ruchu fizycznego - tylko 12% agentow sie poruszalo wobec 28% w Bieliku. Sugeruje to ze model preferuje zastepowanie aktywnosci fizycznych interakcjami online, co jest zachowaniem mniej realistycznym z punktu widzenia modelowania codziennego zycia.

Nalezy zaznaczyc ze Qwen3-30B jest modelem wyspecjalizowanym do generowania kodu (`-Coder`), a nie modelem ogolnego przeznaczenia. Degradacja jakosci symulacji wynika prawdopodobnie z braku odpowiednio wytrenowanego modelu zachowan czlowieka w codziennym zyciu, a nie ze wzgledu na architekture czy rozmiar. Bielik-11B natomiast, trenowany na polskich danych ogolnych, generuje bardziej realistyczne zachowania kulturowo (polskie sklepy, serwisy kulinarne). Glowny wniosek: **specjalizacja modelu ma wiekszy wplyw na jakosc symulacji niz jego rozmiar**.

## 5. Wnioski

**Pozytywne:**
- Model Bielik-11B poprawnie generuje zroznicowane zachowania agentow zgodne z profilem (wiek, zawod, zainteresowania)
- Rozkland aktywnosci internetowej wykazuje realizm - inne zachowania w godzinach pracy vs wieczornych
- Skalowanie jest efektywne dzieki rownoleglemu przetwarzaniu

**Obserwacje do dalszej pracy:**
- Tylko 28% agentow wykonalo ruch fizyczny w ciagu doby - mozliwe zanizynenie wzgledem IRL
- Logowanie surowych wejsc/wyjsc LLM nie jest zaimplementowane - utrudnia bezposrednia analize jakosci odpowiedzi modelu
- Throughput PLGrid (~6k tok/s) ogranicza praktyczna skale symulacji w rozumnym czasie
