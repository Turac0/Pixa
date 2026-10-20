"""Swedish.

``MESSAGES`` maps each English text to its translation. A key "context|text"
translates the text where it is used in that context: "undo|..." are the
names of steps as shown after "Ångra"/"Gör om" (so they start in lower case).
Text that depends on a number has a tuple with one form per ``plural()`` value.
Words in braces are filled in by Pixa and must stay as they are.
"""

NAME = "Svenska"


def plural(n: int) -> int:
    """Which form of a text to use for the number ``n``: 0 for one, 1 for more."""
    return 0 if n == 1 else 1


MESSAGES: dict[str, str | tuple[str, ...]] = {
    # ---- menus and actions
    "&File": "&Arkiv",
    "&Edit": "&Redigera",
    "&Page": "&Sida",
    "&View": "&Visa",
    "&Help": "&Hjälp",
    "Open…": "Öppna…",
    "Open Recent": "Öppna senaste",
    "Save": "Spara",
    "Save As…": "Spara som…",
    "Ask Before Overwriting Originals": "Fråga innan original skrivs över",
    "Print…": "Skriv ut…",
    "Print Preview…": "Förhandsgranska utskrift…",
    "See the pages as they will print": "Se sidorna som de kommer att skrivas ut",
    "Close Document": "Stäng dokument",
    "Quit": "Avsluta",
    "Undo": "Ångra",
    "Redo": "Gör om",
    "Undo {action}": "Ångra {action}",
    "Redo {action}": "Gör om {action}",
    "Paste": "Klistra in",
    "Paste an image from the clipboard": "Klistra in en bild från urklipp",
    "Delete": "Ta bort",
    "Select": "Välj",
    "Edit text": "Redigera text",
    "Add text": "Lägg till text",
    "Add image": "Lägg till bild",
    "Highlight": "Färgmarkera",
    "Add box": "Lägg till ruta",
    "Rotate Left": "Rotera åt vänster",
    "Rotate Right": "Rotera åt höger",
    "Rotate page left": "Rotera sidan åt vänster",
    "Rotate page right": "Rotera sidan åt höger",
    "Delete Page": "Ta bort sida",
    "Delete selected page(s)": "Ta bort markerade sidor",
    "Move Page Up": "Flytta sidan uppåt",
    "Move Page Down": "Flytta sidan nedåt",
    "Insert Blank Page": "Infoga tom sida",
    "Insert Pages from PDF…": "Infoga sidor från PDF…",
    "Insert pages from another PDF": "Infoga sidor från en annan PDF",
    "Arrange": "Ordna",
    "Bring to front": "Lägg längst fram",
    "Bring forward": "Flytta framåt",
    "Send backward": "Flytta bakåt",
    "Send to back": "Lägg längst bak",
    "{action} (the selected text box, image or box)":
        "{action} (den markerade textrutan, bilden eller rutan)",
    "Zoom In": "Zooma in",
    "Zoom Out": "Zooma ut",
    "Fit Width": "Anpassa till bredd",
    "Toggle Theme": "Byt tema",
    "Theme: system / light / dark": "Tema: system / ljust / mörkt",
    "Theme: {mode}": "Tema: {mode}",
    "Theme: {mode} (click to change)": "Tema: {mode} (klicka för att byta)",
    "system": "system",
    "light": "ljust",
    "dark": "mörkt",
    "Language": "Språk",
    "Same as System ({language})": "Samma som systemet ({language})",
    "Language: {language}": "Språk: {language}",
    "Check for Updates…": "Sök efter uppdateringar…",
    "Check for Updates Automatically": "Sök efter uppdateringar automatiskt",
    "About Pixa": "Om Pixa",
    "A clean, local PDF editor.": "En ren och enkel PDF-redigerare som körs lokalt.",
    "Built with PySide6 and PyMuPDF.": "Byggd med PySide6 och PyMuPDF.",

    # ---- welcome screen and files
    "Open a PDF or drop it here to start editing. Dropped images become a new PDF.":
        "Öppna en PDF eller släpp den här för att börja redigera. Bilder som släpps "
        "blir en ny PDF.",
    "Open PDF…": "Öppna PDF…",
    "Recent": "Senaste",
    "PDF documents (*.pdf)": "PDF-dokument (*.pdf)",
    "Open PDF": "Öppna PDF",
    "Password required": "Lösenord krävs",
    "“{name}” is protected. Enter the password:":
        "”{name}” är lösenordsskyddad. Ange lösenordet:",
    "Incorrect password.": "Fel lösenord.",
    "Saved {name}": "Sparade {name}",
    "Save PDF As": "Spara PDF som",
    "{name} (edited)": "{name} (redigerad)",
    "document": "dokument",
    "Untitled": "Namnlös",
    "Overwrite original?": "Skriva över originalet?",
    "Replace “{name}” with your edited version?":
        "Vill du ersätta ”{name}” med din redigerade version?",
    "The original file will be overwritten and can't be recovered. "
    "Choose “Save as Copy…” to keep it unchanged.":
        "Originalfilen skrivs över och kan inte återställas. Välj ”Spara som kopia…” "
        "för att behålla den oförändrad.",
    "Overwrite": "Skriv över",
    "Save as Copy…": "Spara som kopia…",
    "Don't ask again": "Fråga inte igen",
    "Unsaved changes": "Osparade ändringar",
    "Save changes to “{name}” before closing?":
        "Vill du spara ändringarna i ”{name}” innan du stänger?",
    "Your changes will be lost if you don't save them.":
        "Dina ändringar går förlorade om du inte sparar dem.",
    "There is no image on the clipboard to paste.":
        "Det finns ingen bild i urklipp att klistra in.",
    "Inserted {n} page. Undo removes it again.": (
        "Infogade {n} sida. Ångra tar bort den igen.",
        "Infogade {n} sidor. Ångra tar bort dem igen.",
    ),
    "Deleted {n} page. Undo to restore.": (
        "Tog bort {n} sida. Ångra för att återställa.",
        "Tog bort {n} sidor. Ångra för att återställa.",
    ),
    "Inserted {n} page from {name}": (
        "Infogade {n} sida från {name}",
        "Infogade {n} sidor från {name}",
    ),
    "Page {page} of {count}": "Sida {page} av {count}",
    "Choose image": "Välj bild",
    "Insert pages from PDF": "Infoga sidor från PDF",
    "Rotate image left": "Rotera bilden åt vänster",
    "Rotate image right": "Rotera bilden åt höger",
    "Printing page {page} of {count}…": "Skriver ut sida {page} av {count}…",
    "Sent {n} page to the printer.": (
        "Skickade {n} sida till skrivaren.",
        "Skickade {n} sidor till skrivaren.",
    ),
    "Images ({patterns})": "Bilder ({patterns})",
    "All files (*)": "Alla filer (*)",

    # ---- page sidebar
    "Rotate left": "Rotera åt vänster",
    "Rotate right": "Rotera åt höger",
    "Move up": "Flytta upp",
    "Move down": "Flytta ned",
    "Insert blank page after": "Infoga tom sida efter",
    "Insert pages from PDF…": "Infoga sidor från PDF…",
    "Delete page(s)": "Ta bort sidor",

    # ---- right-hand panel
    "Click a text box, image, highlight or box to select it. Drag a text box or box to move "
    "it, or nudge it with the arrow keys (Shift for bigger steps). Delete removes the "
    "selection; right-click it for its layer. Drag thumbnails to reorder pages, or to another "
    "Pixa window to copy them. Drop PDFs and images onto the pages or the thumbnails.":
        "Klicka på en textruta, bild, färgmarkering eller ruta för att markera den. Dra en "
        "textruta eller ruta för att flytta den, eller knuffa den med piltangenterna (Skift "
        "för större steg). Delete tar bort det markerade; högerklicka för att ändra lager. "
        "Dra miniatyrerna för att ändra sidordningen, eller till ett annat Pixa-fönster för "
        "att kopiera dem. Släpp PDF:er och bilder på sidorna eller miniatyrerna.",
    "Hover over text to see editable lines. Click a line to edit it. Enter saves, "
    "Shift+Enter adds a line break, Esc cancels.":
        "Håll pekaren över text för att se rader som går att redigera. Klicka på en rad för "
        "att redigera den. Retur sparar, Skift+Retur lägger till en radbrytning, Esc avbryter.",
    "Click anywhere on a page to start typing. Choose the font, size and colour below. "
    "Enter places the text.":
        "Klicka var som helst på en sida för att börja skriva. Välj typsnitt, storlek och "
        "färg nedan. Retur placerar texten.",
    "Choose an image, then drag it into position and resize it from the corner handle "
    "(Shift for free resize). Enter places it.":
        "Välj en bild, dra den på plats och ändra storleken med hörnhandtaget (Skift för fri "
        "storlek). Retur placerar den.",
    "Drag across text to highlight it, like with a marker. Where there is no text (a scan, "
    "a picture) the dragged area is highlighted. To recolour or remove a highlight, click it "
    "with the Select tool.":
        "Dra över text för att färgmarkera den, som med en överstrykningspenna. Där det inte "
        "finns någon text (en skanning, en bild) markeras området du drar över. Klicka på en "
        "färgmarkering med verktyget Välj för att byta färg på den eller ta bort den.",
    "Drag on a page to draw a box. Choose its border and fill below. To move, resize or "
    "restyle a box later, click it with the Select tool.":
        "Dra på en sida för att rita en ruta. Välj kantlinje och fyllning nedan. Klicka på "
        "rutan med verktyget Välj för att senare flytta den, ändra storlek eller utseende.",
    "Smaller": "Mindre",
    "Larger": "Större",
    "Custom colour…": "Egen färg…",
    "Text": "Text",
    "pt": "pt",
    "bold|B": "F",
    "italic|I": "K",
    "underline|U": "U",
    "Bold": "Fetstil",
    "Italic": "Kursiv",
    "Underline": "Understruken",
    "Highlight colour": "Markeringsfärg",
    "Border": "Kantlinje",
    "No border": "Ingen kantlinje",
    "Border width (0 for no border)": "Kantlinjens bredd (0 för ingen kantlinje)",
    "Border colour": "Kantlinjens färg",
    "Fill": "Fyllning",
    "Fill colour": "Fyllnadsfärg",
    "Image": "Bild",
    "Choose image…": "Välj bild…",
    "Place image": "Placera bild",
    "Cancel": "Avbryt",
    "Drag to move. Corners resize (Shift: free). The round handle rotates (Shift: no "
    "snapping). Arrow keys nudge.":
        "Dra för att flytta. Hörnen ändrar storlek (Skift: fritt). Det runda handtaget "
        "roterar (Skift: utan fästpunkter). Piltangenterna knuffar.",
    "Rotate": "Rotera",
    "Delete image": "Ta bort bild",
    "Text box": "Textruta",
    "Drag to move. Arrow keys nudge by 1 pt, with Shift by 10 pt.":
        "Dra för att flytta. Piltangenterna knuffar 1 pt, med Skift 10 pt.",
    "Delete text box": "Ta bort textruta",
    "Box": "Ruta",
    "noun|Highlight": "Färgmarkering",
    "Drag to move, drag a corner to resize. Arrow keys nudge.":
        "Dra för att flytta, dra i ett hörn för att ändra storlek. Piltangenterna knuffar.",
    "Delete box": "Ta bort ruta",
    "Delete highlight": "Ta bort färgmarkering",
    "To front": "Längst fram",
    "Forward": "Framåt",
    "Backward": "Bakåt",
    "To back": "Längst bak",
    "Bring to front (Ctrl+Shift+Page Up)": "Lägg längst fram (Ctrl+Skift+Page Up)",
    "Bring forward, past what it overlaps (Ctrl+Page Up)":
        "Flytta framåt, förbi det den överlappar (Ctrl+Page Up)",
    "Send backward, behind what it overlaps (Ctrl+Page Down)":
        "Flytta bakåt, bakom det den överlappar (Ctrl+Page Down)",
    "Send to back (Ctrl+Shift+Page Down)": "Lägg längst bak (Ctrl+Skift+Page Down)",
    "Page": "Sida",
    "Blank page": "Tom sida",
    "Insert PDF…": "Infoga PDF…",
    "Delete page": "Ta bort sida",
    "No document": "Inget dokument",
    "Font of this text: {font}": "Den här textens typsnitt: {font}",
    "Text colour": "Textfärg",
    "Helvetica (standard)": "Helvetica (standard)",
    "Times (standard)": "Times (standard)",
    "Courier (standard)": "Courier (standard)",
    "Transparent": "Genomskinlig",
    "Less": "Mindre",
    "More": "Mer",

    # ---- on the pages
    "No text here. Use “Add text” to place new text.":
        "Ingen text här. Använd ”Lägg till text” för att placera ny text.",
    "The box has no border and no fill now, so it is invisible until you give it one.":
        "Rutan har varken kantlinje eller fyllning nu, så den syns inte förrän du ger den "
        "någon av dem.",
    "Give the box a border or a fill colour first.":
        "Ge först rutan en kantlinje eller en fyllnadsfärg.",
    "Drag on the page to draw a box.": "Dra på sidan för att rita en ruta.",
    "Drag across the text you want to highlight.": "Dra över texten du vill färgmarkera.",
    "That file could not be read as an image.": "Filen kunde inte läsas som en bild.",
    "Drag to position, corners resize, the top handle rotates. Enter places, Esc cancels.":
        "Dra för att placera, hörnen ändrar storlek, det övre handtaget roterar. Retur "
        "placerar, Esc avbryter.",
    "The text box is already in front of everything it overlaps.":
        "Textrutan ligger redan framför allt den överlappar.",
    "The text box is already behind everything it overlaps.":
        "Textrutan ligger redan bakom allt den överlappar.",
    "The image is already in front of everything it overlaps.":
        "Bilden ligger redan framför allt den överlappar.",
    "The image is already behind everything it overlaps.":
        "Bilden ligger redan bakom allt den överlappar.",
    "The box is already in front of everything it overlaps.":
        "Rutan ligger redan framför allt den överlappar.",
    "The box is already behind everything it overlaps.":
        "Rutan ligger redan bakom allt den överlappar.",
    "{action}: done. Undo puts the text box back.":
        "{action}: klart. Ångra lägger tillbaka textrutan.",
    "{action}: done. Undo puts the image back.": "{action}: klart. Ångra lägger tillbaka bilden.",
    "{action}: done. Undo puts the box back.": "{action}: klart. Ångra lägger tillbaka rutan.",

    # ---- print dialog and preview
    "Print": "Skriv ut",
    "Save as PDF file": "Spara som PDF-fil",
    "Properties…": "Egenskaper…",
    "The printer's own settings": "Skrivarens egna inställningar",
    "Collate": "Sortera",
    "Print in grayscale (black and white)": "Skriv ut i gråskala (svartvitt)",
    "Printer:": "Skrivare:",
    "Fewer copies": "Färre kopior",
    "More copies": "Fler kopior",
    "Copies:": "Kopior:",
    "All": "Alla",
    "Current page ({page})": "Aktuell sida ({page})",
    "Selected pages ({count})": "Markerade sidor ({count})",
    "Pages:": "Sidor:",
    "e.g. 1-3, 5": "t.ex. 1-3, 5",
    "Pages to print": "Sidor att skriva ut",
    "Fit to paper": "Anpassa till papperet",
    "Actual size": "Verklig storlek",
    "Shrink oversized pages": "Förminska för stora sidor",
    "Custom scale:": "Egen skala:",
    "Page sizing": "Sidstorlek",
    "Paper:": "Papper:",
    "Print on both sides of the paper": "Skriv ut på båda sidorna av papperet",
    "Flip on long edge": "Vänd längs långsidan",
    "Flip on short edge": "Vänd längs kortsidan",
    "Auto": "Automatisk",
    "Portrait": "Stående",
    "Landscape": "Liggande",
    "Paper turned to suit the pages; pages that don't suit it are turned":
        "Papperet vänds efter sidorna; sidor som inte passar vänds",
    "Two-sided and orientation": "Dubbelsidigt och orientering",
    "Orientation:": "Orientering:",
    "Previous page": "Föregående sida",
    "Next page": "Nästa sida",
    "This printer can't print on both sides": "Skrivaren kan inte skriva ut dubbelsidigt",
    "Type page numbers and ranges between 1 and {count}, e.g. 1-3, 5":
        "Ange sidnummer och intervall mellan 1 och {count}, t.ex. 1-3, 5",
    "Paper: {name}, {width} × {height} mm": "Papper: {name}, {width} × {height} mm",
    "No pages": "Inga sidor",
    "Document: {width} × {height} mm": "Dokument: {width} × {height} mm",
    "Save as PDF": "Spara som PDF",
    "Print preview": "Förhandsgranska utskrift",
    "Portrait paper": "Stående papper",
    "Landscape paper": "Liggande papper",
    "All pages": "Alla sidor",
    "Show all pages side by side": "Visa alla sidor bredvid varandra",
    "Fit width": "Anpassa till bredd",
    "Fit the page to the width": "Anpassa sidan till bredden",
    "Fit page": "Hel sida",
    "Show a whole page": "Visa en hel sida",
    "Zoom out": "Zooma ut",
    "Zoom in": "Zooma in",
    "Previous": "Föregående",
    "Next": "Nästa",
    "Close": "Stäng",
    "Could not start printing. Check the printer and try again.":
        "Utskriften kunde inte starta. Kontrollera skrivaren och försök igen.",
    "The printer stopped accepting pages.": "Skrivaren slutade ta emot sidor.",

    # ---- updates
    "Update Available": "Uppdatering tillgänglig",
    "Pixa {version} is available": "Pixa {version} finns tillgänglig",
    "You have version {version}.": "Du har version {version}.",
    "No release notes.": "Inga versionsanteckningar.",
    "Skip This Version": "Hoppa över den här versionen",
    "Later": "Senare",
    "Install and Restart": "Installera och starta om",
    "Download…": "Ladda ned…",
    "Checking for updates…": "Söker efter uppdateringar…",
    "You have the latest version of Pixa ({version}).":
        "Du har den senaste versionen av Pixa ({version}).",
    "Downloading Pixa {version}…": "Laddar ned Pixa {version}…",
    "Updating Pixa": "Uppdaterar Pixa",
    "Couldn't start the installer: {error}": "Installationsprogrammet kunde inte startas: {error}",
    "Couldn't check for updates: {error}": "Det gick inte att söka efter uppdateringar: {error}",
    "This release has no Windows installer.":
        "Den här versionen har inget installationsprogram för Windows.",
    "This release has no checksum to verify the installer with.":
        "Den här versionen saknar en kontrollsumma att verifiera installationsprogrammet med.",
    "Refusing to download the installer over an insecure connection.":
        "Installationsprogrammet laddas inte ned över en osäker anslutning.",
    "Download cancelled.": "Nedladdningen avbröts.",
    "Couldn't download the update: {error}": "Uppdateringen kunde inte laddas ned: {error}",
    "The downloaded installer is damaged (its checksum doesn't match).":
        "Det nedladdade installationsprogrammet är skadat (kontrollsumman stämmer inte).",

    # ---- errors from the document
    "The dropped pages": "De släppta sidorna",
    "Could not open {name}: {error}": "Det gick inte att öppna {name}: {error}",
    "{name} is not a PDF.": "{name} är inte en PDF.",
    "{name} is password protected.": "{name} är lösenordsskyddad.",
    "{name} could not be read.": "{name} kunde inte läsas.",
    "{name} could not be read as an SVG image.": "{name} kunde inte läsas som en SVG-bild.",
    "{name} is an empty SVG image.": "{name} är en tom SVG-bild.",
    "The image": "Bilden",
    "{name} could not be read as an image.": "{name} kunde inte läsas som en bild.",
    "The image could not be converted.": "Bilden kunde inte konverteras.",
    "No file name given": "Inget filnamn angavs",
    "Could not save: {error}": "Det gick inte att spara: {error}",
    "A PDF must keep at least one page.": "En PDF måste ha minst en sida.",
    "Not an SVG image.": "Inte en SVG-bild.",
    "This image can't be moved: it's embedded in a way Pixa can't edit yet (inline or "
    "inside a form).":
        "Bilden kan inte flyttas: den är inbäddad på ett sätt som Pixa inte kan redigera än "
        "(direkt i sidan eller i ett formulär).",
    "An image can't be smaller than 1 point.": "En bild kan inte vara mindre än 1 punkt.",
    "Could not update the image.": "Det gick inte att uppdatera bilden.",
    "Could not insert image: {error}": "Det gick inte att infoga bilden: {error}",
    "Could not insert image.": "Det gick inte att infoga bilden.",
    "Could not delete the image.": "Det gick inte att ta bort bilden.",
    "A box needs a border or a fill colour.": "En ruta behöver en kantlinje eller en fyllnadsfärg.",
    "Only boxes can be moved.": "Bara rutor kan flyttas.",
    "Highlights always lie on top of the page.": "Färgmarkeringar ligger alltid överst på sidan.",
    "The layer of this image can't be changed: it's drawn in a way Pixa can't edit yet "
    "(e.g. inside a form).":
        "Bildens lager kan inte ändras: den är ritad på ett sätt som Pixa inte kan redigera "
        "än (t.ex. i ett formulär).",
    "The layer of this text can't be changed: it's drawn in a way Pixa can't edit yet "
    "(e.g. inside a form).":
        "Textens lager kan inte ändras: den är ritad på ett sätt som Pixa inte kan redigera "
        "än (t.ex. i ett formulär).",
    "The layer of this box can't be changed: it's drawn in a way Pixa can't edit yet "
    "(e.g. inside a form).":
        "Rutans lager kan inte ändras: den är ritad på ett sätt som Pixa inte kan redigera "
        "än (t.ex. i ett formulär).",
    "Could not change the layer.": "Det gick inte att ändra lagret.",
    "Could not change the layer of the image.": "Det gick inte att ändra bildens lager.",
    "“{font}” isn't installed on this computer and the document only contains some of its "
    "characters, so {chars} uses {fallback}.": (
        "”{font}” är inte installerat på datorn och dokumentet innehåller bara några av dess "
        "tecken, så {chars} använder {fallback}.",
        "”{font}” är inte installerat på datorn och dokumentet innehåller bara några av dess "
        "tecken, så {chars} använder {fallback}.",
    ),
    "“{font}” isn't available for these characters in this document or on this computer, "
    "so the text uses {fallback}.":
        "”{font}” finns inte för de här tecknen i dokumentet eller på datorn, så texten "
        "använder {fallback}.",

    # ---- undo steps, shown as "Ångra …" and "Gör om …"
    "undo|Rotate page": "rotera sida",
    "undo|Rotate pages": "rotera sidor",
    "undo|Delete page": "ta bort sida",
    "undo|Delete pages": "ta bort sidor",
    "undo|Reorder pages": "ändra sidordning",
    "undo|Insert page": "infoga sida",
    "undo|Insert pages": "infoga sidor",
    "undo|Insert blank page": "infoga tom sida",
    "undo|Edit text": "redigera text",
    "undo|Add text": "lägg till text",
    "undo|Move text": "flytta text",
    "undo|Delete text": "ta bort text",
    "undo|Transform image": "ändra bild",
    "undo|Add image": "lägg till bild",
    "undo|Add images": "lägg till bilder",
    "undo|Delete image": "ta bort bild",
    "undo|Highlight": "färgmarkering",
    "undo|Change highlight": "ändra färgmarkering",
    "undo|Add box": "lägg till ruta",
    "undo|Change box": "ändra ruta",
    "undo|Resize box": "ändra storlek på ruta",
    "undo|Move box": "flytta ruta",
    "undo|Delete box": "ta bort ruta",
    "undo|Delete highlight": "ta bort färgmarkering",
    "undo|Bring to front": "lägg längst fram",
    "undo|Bring forward": "flytta framåt",
    "undo|Send backward": "flytta bakåt",
    "undo|Send to back": "lägg längst bak",
}
