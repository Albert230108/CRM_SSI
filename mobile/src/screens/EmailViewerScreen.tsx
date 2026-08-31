import { useLayoutEffect } from 'react'
import { Linking, StyleSheet, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { WebView } from 'react-native-webview'
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native'

import type { EmailViewerParams } from '../navigation/types'

type EmailViewerRoute = RouteProp<Record<'EmailViewer', EmailViewerParams>, 'EmailViewer'>

/**
 * Escape a plain-text fallback so it renders literally (never as markup) inside the HTML shell.
 * Used when a message has no HTML body — we still show it in the same styled viewer.
 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/**
 * Wrap raw email HTML (or an escaped plain-text fallback) in a minimal, mobile-friendly document:
 * a responsive viewport so wide emails scale down, a readable base font, and `word-wrap` so long
 * links don't force horizontal scrolling. The email's own inline styles still apply on top.
 */
function buildDocument(html: string | null, fallbackText: string): string {
  const bodyContent =
    html && html.trim().length > 0 ? html : `<pre class="plain">${escapeHtml(fallbackText)}</pre>`
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5" />
<style>
  html, body { margin: 0; padding: 12px; }
  body {
    font-family: -apple-system, Roboto, system-ui, sans-serif;
    font-size: 16px;
    line-height: 1.5;
    color: #111827;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  img, table { max-width: 100% !important; height: auto; }
  pre.plain { white-space: pre-wrap; word-wrap: break-word; font-family: inherit; }
  a { color: #2563eb; }
</style>
</head>
<body>${bodyContent}</body>
</html>`
}

/** Full-screen email renderer. Opened when an email bubble is tapped in the thread. */
export function EmailViewerScreen() {
  const navigation = useNavigation()
  const route = useRoute<EmailViewerRoute>()
  const { subject, html, text } = route.params

  useLayoutEffect(() => {
    navigation.setOptions({ title: subject?.trim() || 'Email' })
  }, [navigation, subject])

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <View style={styles.flex}>
        <WebView
          originWhitelist={['*']}
          source={{ html: buildDocument(html ?? null, text ?? '') }}
          style={styles.webview}
          // Render the inline email statically; if the user taps a link, open it in the system
          // browser rather than navigating inside the WebView (which would strand them off-email).
          onShouldStartLoadWithRequest={(req) => {
            if (/^https?:/i.test(req.url)) {
              void Linking.openURL(req.url)
              return false
            }
            return true
          }}
        />
      </View>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  flex: { flex: 1 },
  webview: { flex: 1, backgroundColor: '#fff' },
})
