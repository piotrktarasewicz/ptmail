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

Stos technologiczny:

- **Język i interfejs:** Python + wxPython, ten sam stos co PT Calendar Manager. Interfejs po polsku, ale od początku z obsługą tłumaczeń (gettext).
- **Pamięć podręczna:** lokalna baza SQLite z nagłówkami i treścią wiadomości z ostatnich 90 dni, żeby listy otwierały się natychmiast. Starsza poczta zostaje tylko na serwerze.
- **Nowa poczta:** IMAP IDLE, czyli serwer sam powiadamia o nowych wiadomościach, bez ciągłego odpytywania.
- **Hasła:** Menedżer poświadczeń Windows (biblioteka keyring), nigdy w pliku konfiguracyjnym.
- **Treść wiadomości:** HTML zamieniony na czysty tekst, bo tylko on zawiera opisy linków, a gdy go brak, część tekstowa maila.

Gmailowe specyfiki: foldery systemowe są w `[Gmail]`, a „Wszystkie wiadomości” i „Ważne” pomijamy przy synchronizacji, bo dublują skrzynkę. Archiwizacja w Gmailu oznacza usunięcie etykiety Odebrane.

## Struktura ekranów

Program ma trzy poziomy, przez które chodzi się jak po drzewie: Enter idzie w głąb, Escape wraca o poziom wyżej. W oknie jest zawsze tylko jeden widok naraz, bez paneli obok siebie.

1. **Skrzynki** (ekran startowy)
   - Wszystkie skrzynki: wspólna skrzynka odbiorcza trzech kont, zawsze pierwsza na liście.
   - Poniżej każde konto z nazwą nadaną przez użytkownika, a pod nim jego foldery: Odebrane, Wysłane, Robocze, Kosz, własne foldery.
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
| Ctrl+U | przełącz przeczytana / nieprzeczytana |
| Ctrl+Shift+F | oflaguj / zdejmij flagę |
| Ctrl+N | nowa wiadomość |
| F5 | sprawdź pocztę teraz |

Klawisz aplikacji (lub Shift+F10) otwiera menu z tymi samymi czynnościami, a przy każdej pozycji jest jej skrót. Po usunięciu lub archiwizacji fokus przechodzi na następną wiadomość i NVDA od razu ją czyta.

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
- Ctrl+R, Ctrl+Shift+R, Ctrl+L, Delete: jak na liście wiadomości.
- Alt+strzałka w dół / w górę: następna / poprzednia wiadomość bez wracania do listy.
- Escape: powrót do listy, fokus na tej samej wiadomości.

Domyślny folder zapisu to Pobrane, z możliwością zmiany w ustawieniach.

## Pisanie wiadomości

Okno pisania ma pola w stałej kolejności Tab: **Od, Do, DW, Temat, Treść, Załączniki, Wyślij**. Przy nowej wiadomości fokus startuje w polu Do, przy odpowiedzi w treści.

- **Od:** lista rozwijana z trzema kontami. Przy odpowiedzi i przekazaniu PT Mail sam wybiera konto, na które przyszła wiadomość. Przy nowej wiadomości domyślne konto z ustawień.
- **Do / DW:** zwykłe pola tekstowe, adresy rozdzielone przecinkiem. Podpowiadanie adresów z wysłanej poczty to etap 2.
- **Treść:** czysty tekst. Przy odpowiedzi cytat oryginału poniżej, poprzedzony linią „W dniu…, … napisał(a):”.
- **Załączniki:** Ctrl+Shift+A otwiera systemowe okno wyboru plików; lista dołączonych plików pod treścią, Delete usuwa plik z listy.
- **Wysyłanie:** Ctrl+Enter. NVDA mówi „Wysłano” i okno się zamyka.
- **Anulowanie:** Escape. Jeśli coś zostało wpisane, jedno pytanie: zapisać w roboczych, odrzucić czy wrócić.

Przekazanie dalej zachowuje oryginalne załączniki. Wysłana wiadomość trafia do folderu Wysłane danego konta (Gmail robi to sam, przy iCloud zapisuje ją PT Mail).

## Fokus i komunikaty

Fokus nigdy nie skacze sam. Zmienia się tylko po działaniu użytkownika i zawsze w przewidywalne miejsce.

- Powrót Escape'em zawsze na ten sam element, z którego się weszło.
- Nowa poczta w tle nie przesuwa zaznaczenia na liście; nowe wiadomości dopisują się na górze.
- Pobieranie i synchronizacja są ciche. Brak paska postępu czytanego przez NVDA.
- Komunikaty statusu („Wysłano”, „Przeniesiono do kosza”) mówione przez NVDA jednym słowem lub krótkim zdaniem, bez okien dialogowych.
- Okno dialogowe tylko wtedy, gdy trzeba podjąć decyzję (np. zapisać szkic). Jedno pytanie, jasne przyciski.
- Błędy połączenia: jedno krótkie zdanie, np. „Brak połączenia z iCloud, spróbuję ponownie”, i żadnego powtarzania przy kolejnych próbach.

Nowa poczta, gdy PT Mail jest w tle: krótki dźwięk i opcjonalne powiadomienie systemowe Windows „Nowa wiadomość od Jan Kowalski”. Oba do wyłączenia w ustawieniach. Program siedzi w zasobniku systemowym i nie zamyka się przy zamknięciu okna (też do wyłączenia).

## Zakres i etapy

Pierwsza używalna wersja (etap 1) ma zastąpić Thunderbirda w codziennym czytaniu i odpowiadaniu na pocztę.

**Etap 1 — MVP**

- [ ] Dodawanie kont: adres + hasło aplikacji, serwery Gmaila i iCloud wpisane z góry
- [ ] Ekran Skrzynki z Wszystkimi skrzynkami i folderami kont
- [ ] Lista wiadomości z czytaniem wiersza i czynnościami
- [ ] Widok wiadomości jako czysty tekst + lista załączników
- [ ] Pisanie: nowa, odpowiedź, odpowiedź wszystkim, przekazanie, załączniki
- [ ] Kosz, archiwizacja, przeczytana/nieprzeczytana, flaga
- [ ] Pamięć podręczna SQLite i IMAP IDLE

**Etap 2 — wygoda**

- [ ] Wyszukiwanie (Ctrl+F) w bieżącej skrzynce i we wszystkich; wiadomości starsze niż 90 dni szukane bezpośrednio na serwerze
- [ ] Podpowiadanie adresów z wysłanej poczty
- [ ] Przenoszenie do folderu
- [ ] Podpis per konto
- [ ] Powiadomienia o nowej poczcie

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
