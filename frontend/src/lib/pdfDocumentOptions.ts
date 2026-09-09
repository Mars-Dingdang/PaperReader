// Shared pdf.js document options for react-pdf <Document options={...}>.
// The object must keep a stable identity: react-pdf re-creates the
// underlying document whenever the `options` prop changes.
//
// cMapUrl lets PDF.js load CID-keyed CJK fonts: translated LaTeX PDFs embed
// Fandol CJK subsets without a ToUnicode map, and without the packed CMap
// files PDF.js fails to load those fonts and silently renders every Chinese
// glyph as blank space. standardFontDataUrl covers the base-14 PDF fonts.
// Both directories are copied into the bundle by vite.config.ts
// (vite-plugin-static-copy) and served at these paths in dev and in the
// packaged app.
export const PDF_DOCUMENT_OPTIONS = {
  cMapUrl: '/cmaps/',
  cMapPacked: true,
  standardFontDataUrl: '/standard_fonts/'
}
