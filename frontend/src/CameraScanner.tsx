import { useEffect, useRef, useState } from 'react'

export default function CameraScanner({ active, onCode }: { active: boolean; onCode: (code: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const onCodeRef = useRef(onCode)
  const lastSeen = useRef({ code: '', at: 0 })
  const [error, setError] = useState('')
  useEffect(() => { onCodeRef.current = onCode }, [onCode])

  useEffect(() => {
    if (!active) return
    if (!window.isSecureContext || !navigator.mediaDevices) return
    let disposed = false
    let controls: { stop: () => void } | undefined
    const video = videoRef.current
    if (!video) return
    void import('@zxing/browser').then(({ BrowserQRCodeReader }) => {
      if (disposed) return
      const reader = new BrowserQRCodeReader()
      return reader.decodeFromVideoDevice(undefined, video, (result) => {
        if (!result || disposed) return
        const code = result.getText()
        const now = Date.now()
        if (lastSeen.current.code === code && now - lastSeen.current.at < 1400) return
        lastSeen.current = { code, at: now }
        onCodeRef.current(code)
      })
    }).then((session) => {
      if (!session) return
      if (disposed) session.stop()
      else controls = session
    }).catch(() => { if (!disposed) setError('无法开启摄像头，请检查权限或改用编号输入') })
    return () => {
      disposed = true
      controls?.stop()
      if (video.srcObject instanceof MediaStream) video.srcObject.getTracks().forEach((track) => track.stop())
    }
  }, [active])

  if (!active) return null
  if (!window.isSecureContext || !navigator.mediaDevices) return <p className="scanner-message">当前地址无法调用摄像头。请使用 HTTPS，或输入编号。</p>
  return <div className="camera-frame"><video ref={videoRef} muted playsInline autoPlay aria-label="扫码摄像头画面" />{error && <p className="scanner-message">{error}</p>}</div>
}
