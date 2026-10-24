# Changelog

## 0.5.4

### New

- **Select several things at once.** With the Select tool, Shift-click (or Ctrl-click; ⌘-click on a Mac) to add text, images, highlights and boxes to the selection, or drag across an empty spot of a page to select everything the rectangle touches. Drag any of them, or use the arrow keys, to move them all together. Delete removes them all. Either way it's a single step to undo.
- **Pinch to zoom.** Zooming with two fingers on a touchpad now works, on a Mac and on Windows.

### Improved

- **Zoom stays where you're looking.** Ctrl+scroll and pinching zoom towards the mouse pointer. The zoom buttons and shortcuts zoom towards the middle of the window instead of jumping to the top left.
- **The Select tool picks single lines of text**, like the Edit text tool, instead of sometimes grabbing a whole block of text at once.
- **Enter starts a new line** when you add or edit text. Click outside the text when you're done (or press Ctrl+Enter, ⌘+Enter on a Mac); Esc still cancels.

## 0.5.3

### Improved

- **Updates now come straight from Pixa's own project page.** Pixa's source code is public now, so **Help → Check for Updates…** and the automatic check look for new versions at [github.com/Turac0/Pixa](https://github.com/Turac0/Pixa/releases), the same place you can download them by hand. Downloads are still checked against their checksum before they're installed.
- **Safer releases.** The installers are built and published in separate, locked-down steps, so the files your copy of Pixa downloads can't be altered along the way.
- **Works with PyMuPDF 2**, the newest version of the PDF engine Pixa is built on. Its large optional add-ons are left out, so the download doesn't grow.

### Other

- **Pixa is free software** under the GNU Affero General Public License v3.0 or later. The license is in the `LICENSE` file and at the end of the README.

## 0.5.2

### New

- **Pixa speaks Swedish.** It uses your system's language when Pixa has it, and English otherwise. Pick a language yourself under **View → Language**. The window switches right away and keeps the open document, unsaved changes and undo history. Qt's standard dialogs and buttons follow the chosen language too.

### Fixed

- **The right-hand panel no longer cuts off its buttons.** It used to clip on the right, sometimes hiding whole buttons, for example while a box without fill was selected or with a long font name in the document. The panel is now as wide as its contents need and keeps that width when you switch tools. The Custom colour buttons show the colour in their round chip, and its code in the tooltip.

## 0.5.1

### New

- **Automatic updates.** Pixa checks for a new version when it starts and shows what's new. On Windows, **Install and Restart** downloads the installer, checks that it arrived intact, installs it and opens the new version. You can also pick **Skip This Version** or **Later**. Use **Help → Check for Updates…** to look right away, and turn off **Help → Check for Updates Automatically** if you'd rather not have it check.

### Improved

- **A more polished, consistent look.** Number boxes (copies and custom scale when printing, text size and border width in the side panel) now have the same − and + buttons everywhere, and any other number box gets clear up and down arrows. Checkboxes and radio buttons are drawn in Pixa's own style, and are easy to see in dark mode too. Text fields show which one has focus.
- **The print dialog matches the rest of the app.** Its sections are rounded cards with headings like the side panel's, the preview sits on the same background as the pages in the editor, and page navigation uses Pixa's icons. Cancel and Print sit at the bottom right in the same order as in the print preview. The print preview window got the same treatment.
- **Smoother colour swatches.** The round colour buttons are now drawn with smooth edges, and the chosen colour gets a clear ring around it. The Custom colour button shows the current colour, and the black swatch is now true black, so the default text colour shows as chosen.
- Recent files on the start screen look like links in the theme's accent colour.

## 0.5.0

### New

- **A new print dialog** replaces the system one. It shows a live preview of what will print, and lets you choose the printer or save as a PDF file, copies, grayscale, page ranges like `1-3, 5`, fit to paper, actual size, shrink oversized pages or a custom scale, paper size, two-sided printing (flip on long or short edge) and orientation. On Windows, **Properties…** opens the printer's own settings, and the paper, orientation, copies, two-sided and colour chosen there carry over.
- **Paste images with Ctrl+V** (Edit → Paste). Copied pixels, or image files copied in your file manager, are placed in the middle of the visible part of the current page and selected, just like a dropped image. While you are editing text, Ctrl+V still pastes text.
- **More image formats.** SVG (and .svgz) files are inserted as sharp vector graphics that you can select, move, resize, rotate, layer and delete like any other image. WebP, ICO, TGA, XPM, and HEIC or AVIF where your system can read them, are converted automatically. This works from Add Image, drag & drop and paste alike.

### Fixed

- Text in some PDFs got wider spacing every time it was moved or edited and turned into garbled characters after a few edits. Edited text in those files now stays exactly as typed.
