# PT Mail — specyfikacja

Stan na: 30 października 2026

## Cel i zasady

PT Mail to prosty klient poczty na Windows dla jednego użytkownika pracującego z NVDA. Wzorem jest Poczta Apple na iPhonie: prostota, przewidywalność, wspólna skrzynka odbiorcza i załączniki na dole wiadomości.

Zasady, którymi kierujemy się przy każdej decyzji:

1. **Prostota ponad funkcje.** Tylko to, czego naprawdę się używa. Funkcje zaawansowane świadomie pomijamy.
2. **Przewidywalność.** Ten sam klawisz zawsze robi to samo, fokus zawsze wraca tam, skąd przyszedł.
3. **Cisza.** Żadnych wyskakujących okien, wstążek, paneli, które same się pojawiają, ani niechcianych powiadomień.
4. **Natywne kontrolki.** Wyłącznie standardowe kontrolki Windows, żeby NVDA czytał je bez ramek i obejść.
5. **Szybkość.** Program pokazuje od razu to, co ma, a nowości dociąga w tle.

## Konta i technologia

Wszystkie trzy konta obsługujemy jednym protokołem: IMAP do odbioru i SMTP do wysyłki, logowanie hasłem aplikacji. Jedna ścieżka kodu, bez OAuth i wygasających tokenów.

| Konto | Serwer IMAP | Serwer SMTP | Logowanie |
| --- | --- | --- | --- |
| Gmail 1 | imap.gmail.com:993 (SSL) | smtp.gmail.com:587 (STARTTLS) | hasło aplikacji Google (wymaga weryfikacji dwuetapowej) |
| Gmail 2 | imap.gmail.com:993 (SSL) | smtp.gmail.com:587 (STARTTLS) | hasło aplikacji Google |
| iCloud | imap.mail.me.com:993 (SSL) | smtp.mail.me.com:587 (STARTTLS) | hasło aplikacji Apple ID |
| Interia | poczta.interia.pl:993 (SSL) | poczta.interia.pl:587 (STARTTLS) | zwykłe hasło konta; w ustawieniach poczty trzeba włączyć dostęp dla programów pocztowych |

Interia nie ogłasza polecenia MOVE, więc PT Mail przenosi wiadomość przez kopię, a potem usuwa oryginał. Role folderów bierze z polecenia XLIST. Wysłaną pocztę do folderu Wysłane zapisuje PT Mail.

Stos technologiczny:

- **Język i interfejs:** Python + wxPython, ten sam stos co PT Calendar Manager. Interfejs po polsku, ale od początku z obsługą tłumaczeń (gettext).
- **Pamięć podręczna:** lokalna baza SQLite z nagłówkami z ostatnich 90 dni i treścią wiadomości już otwartych (do 10 MB każda), żeby listy i przeczytana poczta otwierały się natychmiast, także bez internetu. Starsza poczta zostaje tylko na serwerze. Baza nie jest szyfrowana i leży w `%APPDATA%\PT Mail\cache.db`.
- **Nowa poczta:** IMAP IDLE na osobnym połączeniu z folderem Odebrane, czyli serwer sam powiadamia o nowych wiadomościach, bez ciągłego odpytywania. Inne foldery odświeża F5.
- **Hasła:** Menedżer poświadczeń Windows (biblioteka keyring), nigdy w pliku konfiguracyjnym.
- **Treść wiadomości:** HTML zamieniony na czysty tekst, bo tylko on zawiera opisy linków, a gdy go brak, część tekstowa maila.

Gmailowe specyfiki: foldery systemowe są w `[Gmail]`, a „Wszystkie wiadomości” i „Ważne” pomijamy przy synchronizacji, bo dublują skrzynkę. Archiwizacja w Gmailu oznacza usunięcie etykiety Odebrane.

## Struktura ekranów

Program ma trzy poziomy, przez które chodzi się jak po drzewie: Enter idzie w głąb, Escape wraca o poziom wyżej. W oknie jest zawsze tylko jeden widok naraz, bez paneli obok siebie.

1. **Skrzynki** (ekran startowy)
   - Wszystkie skrzynki: wspólna skrzynka odbiorcza trzech kont, zawsze pierwsza na liście.
   - Poniżej każde konto z nazwą nadaną przez użytkownika (Enter otwiera jego Odebrane), a pod nim jego foldery: Odebrane, Wysłane, Robocze, Kosz, własne foldery. Wiersz folderu kończy nazwa konta, np. „Odebrane, 2 nieprzeczytane, iCloud”.
   - Przy każdej pozycji liczba nieprzeczytanych, np. „Wszystkie skrzynki, 3 nieprzeczytane”.
2. **Lista wiadomości** wybranej skrzynki, od najnowszej.
3. **Wiadomość**: treść, a na dole załączniki.

Okno pisania wiadomości to osobne okno, otwierane z dowolnego poziomu. Po wysłaniu lub anulowaniu fokus wraca dokładnie tam, gdzie był.

Program startuje od razu na liście wiadomości ze Wszystkich skrzynek, na najnowszej wiadomości. Escape z listy przenosi do ekranu Skrzynki.

## Lista wiadomości

Każdy wiersz NVDA czyta jednym zdaniem, zawsze w tej samej kolejności, a części puste są pomijane.

Kolejność: **status, nadawca, temat, załączniki, konto, data**. Przykład: „nieprzeczytana, Jan Kowalski, Faktura za październik, 2 załączniki, iCloud, 13:20”.

- Status mówimy tylko dla wiadomości nieprzeczytanych i oflagowanych; „przeczytana” nie jest czytane.
- Konto podajemy tylko w Wszystkich skrzynkach.
- Data: dziś sama godzina, wczoraj „wczoraj”, w tym tygodniu dzień tygodnia, starsze pełna data.
- Wątki nie są grupowane, każda wiadomość to osobny wiersz.

Czynności na zaznaczonej wiadomości (odpowiednik pokrętła czynności VoiceOvera). Wszystkie skróty działają tylko w oknie PT Mail, żaden nie jest globalny:

| Klawisz | Czynność |
| --- | --- |
| Enter | otwórz wiadomość |
| Ctrl+R | odpowiedz |
| Ctrl+Shift+R | odpowiedz wszystkim |
| Ctrl+L | przekaż dalej |
| Delete | przenieś do kosza |
| Ctrl+Shift+A | archiwizuj |
| Ctrl+M | przenieś do folderu |
| Ctrl+U | przełącz przeczytana / nieprzeczytana |
| Ctrl+Shift+F | oflaguj / zdejmij flagę |
| Ctrl+N | nowa wiadomość |
| F5 | sprawdź pocztę teraz |
| Ctrl+F | szukaj, działa też na ekranie Skrzynki |

Klawisz aplikacji (lub Shift+F10) otwiera menu z tymi samymi czynnościami, a przy każdej pozycji jest jej skrót. Po usunięciu lub archiwizacji fokus przechodzi na następną wiadomość i NVDA od razu ją czyta; gdy starszej nie ma, na poprzednią.

Delete, Ctrl+Shift+A, Ctrl+M, Ctrl+U i Ctrl+Shift+F działają też w widoku wiadomości. Usunięcie, archiwizacja lub przeniesienie wraca wtedy na listę, na następną wiadomość.

Po Delete NVDA czyta od razu następną wiadomość, bez komunikatu „Przeniesiono do kosza”, który przy kasowaniu serii męczy. Komunikat pada tylko wtedy, gdy lista została pusta, a na pasku stanu jest zawsze.

Delete w Koszu nic nie usuwa: PT Mail nie kasuje poczty na stałe. W Gmailu archiwizować można tylko z Odebranych.

## Widok wiadomości i załączniki

Wiadomość otwiera się jako jedno pole tekstowe tylko do odczytu, czytane strzałkami jak dokument. Fokus ląduje na początku treści.

Układ pola, od góry:

1. Sama treść jako czysty tekst, bez nagłówka. Nadawcę, temat i datę czyta się z wiersza na liście. Obrazki są pomijane, chyba że są linkiem i mają opis.
2. Na końcu linia „Załączniki: 2” (lub „Brak załączników”).

Linki czytane są swoim opisem, a adres pozostaje ukryty. Link bez opisu ma etykietę z domeną, np. „link allegro.pl”.

| Klawisz w treści | Czynność |
| --- | --- |
| Enter na linku | otwórz w domyślnej przeglądarce |
| Alt+L | następny link |
| Alt+Shift+L | poprzedni link |
| Alt+A | przeczytaj domenę linku; pełny adres pojawia się na pasku stanu |

Tab przenosi z treści do **listy załączników** pod polem tekstowym. Każdy wiersz: nazwa pliku, typ, rozmiar, np. „faktura.pdf, PDF, 120 KB”.

| Klawisz na liście załączników | Czynność |
| --- | --- |
| Enter | otwórz w domyślnym programie |
| Ctrl+S | zapisz jako… |
| Ctrl+Shift+S | zapisz wszystkie do folderu |

Skróty dostępne w całym oknie wiadomości:

- Alt+Z: skok prosto do listy załączników, bez przechodzenia Tabem.
- Ctrl+R, Ctrl+Shift+R, Ctrl+L, Delete, Ctrl+Shift+A, Ctrl+U, Ctrl+Shift+F: jak na liście wiadomości.
- Alt+strzałka w dół / w górę: następna / poprzednia wiadomość bez wracania do listy.
- Escape: powrót do listy, fokus na tej samej wiadomości.

Domyślny folder zapisu to Pobrane, z możliwością zmiany w ustawieniach.

## Pisanie wiadomości

Okno pisania ma pola w stałej kolejności Tab: **Od, Do, DW, Temat, Treść, Załączniki, Wyślij**. Przy nowej wiadomości fokus startuje w polu Do, przy odpowiedzi w treści.

- **Od:** lista rozwijana z kontami. Przy odpowiedzi i przekazaniu PT Mail sam wybiera konto, na które przyszła wiadomość. Przy nowej wiadomości pierwsze konto na liście w oknie Konta.
  Adresat widzi imię i nazwisko podane przy koncie w oknie Konta, a gdy pole jest puste, sam adres.
- **Do / DW:** zwykłe pola tekstowe, adresy rozdzielone przecinkiem. Po dwóch literach i chwili przerwy w pisaniu NVDA mówi podpowiedź z wysłanej poczty, np. „Anna Kowalska, anna@example.com, 1 z 2”. Pasuje początek adresu lub dowolnego słowa z nazwy, a najczęściej używane adresy są pierwsze. Strzałki w górę i w dół zmieniają podpowiedź, Enter wstawia ją i zostaje w polu, Escape ukrywa, a Tab po prostu idzie dalej.
  Adresy pochodzą z pól Do i DW 500 najnowszych wiadomości z folderu Wysłane każdego konta. Program czyta je raz po starcie, bez treści wiadomości, i dopisuje adresatów każdej wysłanej wiadomości. Podpowiedzi są wspólne dla wszystkich kont.
- **Podpis:** ustawiany przy koncie w oknie Konta. Staje pod treścią, a nad cytatem, po linii „-- ”. Zmiana konta w polu Od zmienia też podpis.
- **Treść:** czysty tekst. Przy odpowiedzi cytat oryginału poniżej, poprzedzony linią „W dniu…, … napisał(a):”.
- **Załączniki:** Ctrl+Shift+A otwiera systemowe okno wyboru plików; lista dołączonych plików pod treścią, Delete usuwa plik z listy.
- **Wysyłanie:** Ctrl+Enter. NVDA mówi „Wysłano” i okno się zamyka.
- **Anulowanie:** Escape. Jeśli coś zostało wpisane, jedno pytanie: zapisać w roboczych, odrzucić czy wrócić.

Przekazanie dalej zachowuje oryginalne załączniki. Wysłana wiadomość trafia do folderu Wysłane danego konta (Gmail robi to sam, przy iCloud zapisuje ją PT Mail).

## Fokus i komunikaty

Fokus nie skacze sam. Zmienia się po działaniu użytkownika, zawsze w przewidywalne miejsce, a jedynym wyjątkiem jest nowa wiadomość na widocznej liście.

- Powrót Escape'em zawsze na ten sam element, z którego się weszło.
- Nowa wiadomość dopisuje się na górze, a zaznaczenie przechodzi na najnowszą i NVDA ją czyta. Dotyczy to tylko widocznej listy wiadomości: czytanie treści i pisanie nie są przerywane, a gdy program jest w tle, zaznaczenie przechodzi po cichu.
- Pobranie poczty na żądanie (start, F5) kończy krótki dźwięk, a nowa poczta ma własny, dwutonowy. Automatyczne odświeżenie bez nowej poczty jest ciche. Brak paska postępu czytanego przez NVDA.
- Komunikaty statusu („Wysłano”, „Przeniesiono do kosza”) mówione przez NVDA jednym słowem lub krótkim zdaniem, bez okien dialogowych.
- Okno dialogowe tylko wtedy, gdy trzeba podjąć decyzję (np. zapisać szkic). Jedno pytanie, jasne przyciski.
- Błędy połączenia: jedno krótkie zdanie, np. „Brak połączenia z iCloud, spróbuję ponownie”, i żadnego powtarzania przy kolejnych próbach.

Nowa poczta, gdy PT Mail jest w tle: krótki dźwięk i powiadomienie systemowe Windows „Nowa wiadomość od Jan Kowalski” z tematem. Powiadomienie wyłącza pozycja „Powiadomienia systemowe” w menu Plik. Przy starcie programu powiadomień nie ma, a gdy kilka wiadomości przyjdzie naraz, jedno powiadomienie mówi o najnowszej.

## Zakres i etapy

Pierwsza używalna wersja (etap 1) ma zastąpić Thunderbirda w codziennym czytaniu i odpowiadaniu na pocztę.

**Etap 1 — MVP**

- [x] Dodawanie kont: adres + hasło aplikacji, serwery Gmaila i iCloud wpisane z góry
- [x] Ekran Skrzynki z Wszystkimi skrzynkami i folderami kont
- [x] Lista wiadomości z czytaniem wiersza i czynnościami
- [x] Widok wiadomości jako czysty tekst + lista załączników
- [x] Pisanie: nowa, odpowiedź, odpowiedź wszystkim, przekazanie, załączniki
- [x] Kosz, archiwizacja, przeczytana/nieprzeczytana, flaga
- [x] Pamięć podręczna SQLite i IMAP IDLE

**Etap 2 — wygoda**

- [x] Wyszukiwanie (Ctrl+F) w bieżącej skrzynce i we wszystkich; zawsze na serwerze, więc obejmuje też pocztę starszą niż 90 dni. „We wszystkich” pomija Kosz i Spam. Okno wyszukiwania zostaje otwarte do końca szukania: NVDA mówi „Wyszukiwanie”, Escape przerywa, a przy braku wyników można od razu poprawić zapytanie. Wyniki pokazuje lista wiadomości, a Escape wraca tam, skąd się przyszło
- [x] Podpowiadanie adresów z wysłanej poczty
- [x] Przenoszenie do folderu
- [x] Podpis per konto
- [x] Powiadomienia o nowej poczcie

**Etap 3 — codzienne używanie**

- [x] Zasobnik systemowy: Alt+F4 chowa program, a poczta i powiadomienia działają dalej. Pozycja „Alt+F4 chowa do zasobnika” w menu Plik przywraca zwykłe zamykanie. Enter na ikonie otwiera okno, klawisz menu pokazuje Otwórz, Sprawdź pocztę teraz i Zakończ. Etykieta ikony podaje liczbę nieprzeczytanych. Program kończy Ctrl+Q albo Zakończ
- [x] Jedna kopia programu: drugie uruchomienie pokazuje okno działającej kopii
- [x] Instalator dla jednego użytkownika, bez pytania o uprawnienia administratora, z pozycją w menu Start, odinstalowaniem oraz wyborem startu z Windows i skrótu na pulpicie. Dane, konta i hasła zostają przy odinstalowaniu
- [x] Start z Windows: program od razu chowa się do zasobnika i jest cichy, nie mówi o błędach połączenia ani o udanym pobraniu poczty
- [x] Aktualizacje z wydań na GitHubie: sprawdzane po starcie i raz na dobę oraz na żądanie z menu Plik. Program pyta o zgodę tylko przy widocznym oknie bez innych otwartych okien. Pytaniu towarzyszy dźwięk systemowy, a gdy program jest w tle, także powiadomienie. Po zgodzie okno z paskiem postępu i przyciskiem Anuluj pobiera instalator, NVDA mówi co 25 procent, a program sprawdza sumę kontrolną. Instalator pokazuje własne okno postępu, po czym program uruchamia się ponownie i mówi „Zaktualizowano do wersji…” albo zgłasza błąd. Błędy mają systemowy dźwięk błędu. Odmowa lub anulowanie obowiązuje do następnego uruchomienia

**Celowo pomijamy:** kalendarz, kontakty, zadania, widok HTML, grupowanie w wątki, filtry i reguły, szyfrowanie, motywy wyglądu.

## Ustalenia

Decyzje podjęte 30 października 2026:

| Temat | Decyzja |
| --- | --- |
| Skróty na liście | Z Ctrl, działające tylko w PT Mail (nie globalne) |
| Delete w Gmailu | Przenosi do kosza |
| Poczta na komputerze | Ostatnie 90 dni; starsza przez wyszukiwanie na serwerze lub stronę WWW |
| Język | Na razie tylko polski, z obsługą tłumaczeń od początku |
| Repozytorium | Publiczne na GitHubie |
| Widok wiadomości | Enter otwiera samą treść, bez linii Od, Do, Data, Temat |
| Linki | Działające linki w polu tekstowym, bez widoku HTML i bez czytania adresów |
| Nowa poczta | Dźwięk po pobraniu, a zaznaczenie przechodzi na nową wiadomość |
