import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { basicSetup } from 'codemirror'
import { EditorSelection, EditorState } from '@codemirror/state'
import { EditorView } from '@codemirror/view'
import { StreamLanguage } from '@codemirror/language'
import { stex } from '@codemirror/legacy-modes/mode/stex'
import { openSearchPanel, replaceAll, SearchQuery, search, setSearchQuery } from '@codemirror/search'

export type TexEditorHandle = {
  goToLine: (line: number) => void
  openSearch: (search?: string, replace?: string) => void
  replaceAllMatches: (search: string, replace: string) => number
  setContent: (content: string) => void
  focus: () => void
}

type Props = {
  initialContent: string
  onChange: (value: string) => void
}

/**
 * CodeMirror 6 LaTeX editor. Lazily imported by TexEditorModal so the
 * editor bundle never loads until the user opens the TeX editor.
 * basicSetup ships the Ctrl+F / Ctrl+H search panel (with match
 * highlighting and replace-all); the imperative handle exposes line jumps
 * and prefilled searches for compile-error panels.
 */
export const TexEditor = forwardRef<TexEditorHandle, Props>(function TexEditor(
  { initialContent, onChange },
  ref
) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const viewRef = useRef<EditorView | null>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEffect(() => {
    if (!hostRef.current) return
    const view = new EditorView({
      state: EditorState.create({
        doc: initialContent,
        extensions: [
          basicSetup,
          StreamLanguage.define(stex),
          EditorView.lineWrapping,
          search({ top: true }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              onChangeRef.current(update.state.doc.toString())
            }
          })
        ]
      }),
      parent: hostRef.current
    })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
    // The modal remounts this component (key) when a different document loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useImperativeHandle(
    ref,
    () => ({
      goToLine(line: number) {
        const view = viewRef.current
        if (!view) return
        const clamped = Math.min(Math.max(1, line), view.state.doc.lines)
        const target = view.state.doc.line(clamped)
        view.dispatch({
          selection: EditorSelection.cursor(target.from),
          effects: EditorView.scrollIntoView(target.from, { y: 'center' })
        })
        view.focus()
      },
      openSearch(searchText?: string, replaceText?: string) {
        const view = viewRef.current
        if (!view) return
        if (searchText != null) {
          view.dispatch({
            effects: setSearchQuery.of(
              new SearchQuery({ search: searchText, replace: replaceText })
            )
          })
        }
        openSearchPanel(view)
        view.focus()
      },
      replaceAllMatches(searchText: string, replaceText: string): number {
        const view = viewRef.current
        if (!view) return 0
        const occurrences = view.state.sliceDoc().split(searchText).length - 1
        if (occurrences > 0) {
          view.dispatch({
            effects: setSearchQuery.of(
              new SearchQuery({ search: searchText, replace: replaceText })
            )
          })
          replaceAll(view)
        }
        return occurrences
      },
      setContent(content: string) {
        const view = viewRef.current
        if (!view) return
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: content }
        })
      },
      focus() {
        viewRef.current?.focus()
      }
    }),
    []
  )

  return <div ref={hostRef} className="tex-editor-host" />
})
