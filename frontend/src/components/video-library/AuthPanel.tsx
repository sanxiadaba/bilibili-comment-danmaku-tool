import { KeyRound, Loader2, QrCode, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import QRCode from "qrcode";
import { clearCookie, createAuthQrCode, pollAuthQrCode, saveCookie } from "../../api/client";
import { cn } from "../../lib/utils";
import type { AuthQrPollResponse, AuthQrSession, CookieStatus } from "../../types";

type AuthPanelProps = {
  cookieStatus?: CookieStatus | null;
  onStatusChange: (status: CookieStatus | null) => void;
};

export function AuthPanel({ cookieStatus, onStatusChange }: AuthPanelProps) {
  const [cookieText, setCookieText] = useState("");
  const [qrSession, setQrSession] = useState<AuthQrSession | null>(null);
  const [qrState, setQrState] = useState<AuthQrPollResponse | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isClearing, setIsClearing] = useState(false);
  const [isCreatingQr, setIsCreatingQr] = useState(false);
  const [qrImageUrl, setQrImageUrl] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);
  const qrTtl = useMemo(() => qrState?.ttl_seconds ?? qrSession?.ttl_seconds ?? 0, [qrSession, qrState]);

  useEffect(() => {
    if (!qrSession?.url) {
      setQrImageUrl("");
      return;
    }
    let active = true;
    QRCode.toDataURL(qrSession.url, { margin: 1, width: 180 })
      .then((dataUrl) => {
        if (active) setQrImageUrl(dataUrl);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      active = false;
    };
  }, [qrSession]);

  useEffect(() => {
    if (!qrSession || qrState?.status === "confirmed" || qrState?.status === "expired") return;
    const timer = window.setInterval(async () => {
      try {
        const payload = await pollAuthQrCode(qrSession.session_id);
        setQrState(payload);
        setMessage(payload.message || "");
        if (payload.cookie_status) {
          onStatusChange(payload.cookie_status);
        }
        if (payload.status === "confirmed" || payload.status === "expired") {
          window.clearInterval(timer);
        }
      } catch (reason: unknown) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }, 1800);
    return () => window.clearInterval(timer);
  }, [onStatusChange, qrSession, qrState?.status]);

  async function startQrLogin() {
    setError("");
    setMessage("");
    setIsCreatingQr(true);
    try {
      const payload = await createAuthQrCode();
      setQrSession(payload);
      setQrState({ ok: false, status: "waiting", code: 86101, message: "等待扫码", login_url: "", expires_at: payload.expires_at, ttl_seconds: payload.ttl_seconds });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsCreatingQr(false);
    }
  }

  async function submitCookie(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setIsSaving(true);
    try {
      const payload = await saveCookie(cookieText);
      onStatusChange(payload);
      setCookieText("");
      setMessage(payload.message || "Cookie 已保存");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsSaving(false);
    }
  }

  async function clearLogin() {
    setError("");
    setMessage("");
    setIsClearing(true);
    try {
      const payload = await clearCookie();
      onStatusChange(payload);
      setQrSession(null);
      setQrState(null);
      setMessage("登录态已清除");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setIsClearing(false);
    }
  }

  async function importCookieFile(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setError("");
    try {
      setCookieText(await file.text());
      setMessage(`已读取 ${file.name}`);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  const statusTone = cookieStatus?.status === "valid" ? "text-emerald-700" : cookieStatus?.exists ? "text-amber-700" : "text-muted";

  return (
    <section className="rounded-md border border-line bg-white shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-ink">
            <KeyRound size={18} aria-hidden="true" />
            登录态管理
          </h2>
          <div className={cn("mt-1 text-sm", statusTone)}>{cookieStatus?.message || "正在检测本地登录态"}</div>
        </div>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:border-red-300 hover:text-red-700 disabled:cursor-wait disabled:opacity-70"
          type="button"
          disabled={isClearing}
          onClick={clearLogin}
        >
          <Trash2 size={16} aria-hidden="true" />
          清除
        </button>
      </div>

      <div className="grid gap-4 p-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="grid content-start gap-3 rounded-md border border-line bg-[#fbfcfe] p-3">
          <div className="text-sm font-semibold text-ink">扫码登录</div>
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-white transition hover:bg-[#26344f] disabled:cursor-wait disabled:opacity-70"
            type="button"
            disabled={isCreatingQr}
            onClick={startQrLogin}
          >
            {isCreatingQr ? <Loader2 className="animate-spin" size={16} aria-hidden="true" /> : <QrCode size={16} aria-hidden="true" />}
            生成二维码
          </button>
          {qrImageUrl && (
            <div className="grid justify-items-center gap-2 rounded-md border border-line bg-white p-3">
              <img className="h-[180px] w-[180px]" src={qrImageUrl} alt="Bilibili 登录二维码" />
              <div className="text-center text-sm text-muted">{qrState?.message || "等待扫码"}</div>
              <div className="text-xs text-muted">剩余 {qrTtl}s</div>
            </div>
          )}
        </div>

        <form className="grid content-start gap-3 rounded-md border border-line bg-[#fbfcfe] p-3" onSubmit={submitCookie}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-semibold text-ink">手动 Cookie</div>
              <div className="mt-1 text-xs text-muted">支持普通 Cookie 字符串或 Netscape cookie 文件内容。</div>
            </div>
            <button
              className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:border-bilibili hover:text-bilibili"
              type="button"
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={16} aria-hidden="true" />
              导入文件
            </button>
          </div>
          <textarea
            className="min-h-28 rounded-md border border-line bg-white p-3 text-sm text-ink outline-none focus:border-bilibili focus:ring-2 focus:ring-pink-100"
            placeholder="SESSDATA=...; bili_jct=...; DedeUserID=..."
            value={cookieText}
            onChange={(event) => setCookieText(event.target.value)}
          />
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-bilibili px-4 text-sm font-medium text-white transition hover:bg-[#e85f89] disabled:cursor-wait disabled:opacity-70"
            type="submit"
            disabled={isSaving}
          >
            {isSaving ? <Loader2 className="animate-spin" size={16} aria-hidden="true" /> : <KeyRound size={16} aria-hidden="true" />}
            保存并检测
          </button>
          <input ref={fileRef} className="hidden" type="file" accept=".txt,.cookies" onChange={(event) => void importCookieFile(event.target.files)} />
        </form>
      </div>

      {(message || error) && (
        <div className={cn("border-t border-line px-4 py-3 text-sm", error ? "text-red-700" : "text-emerald-700")}>
          {error || message}
        </div>
      )}
    </section>
  );
}
