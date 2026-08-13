"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Bell, CheckCheck } from "lucide-react";
import { notificationsApi } from "@/lib/api-client";

interface NotificationItem {
  id: string;
  type: string;
  message: string;
  link: string | null;
  league_id: string | null;
  is_read: boolean;
  created_at: string;
}

const POLL_INTERVAL_MS = 60_000;

function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Proactive "N new notifications" announcement for screen-reader users --
  // the bell's aria-label already reports the current count, but that's
  // only read when the bell itself is focused. Without this, someone
  // reading elsewhere on the page while the 60s poll picks up a new
  // notification has no way to know one arrived. Only fires on an actual
  // *increase* (not the poll re-confirming an unchanged count, and not a
  // mark-as-read decrease, which isn't news).
  const prevUnreadRef = useRef(0);
  const [announcement, setAnnouncement] = useState("");

  const refresh = useCallback(() => {
    notificationsApi
      .list()
      .then((data) => {
        const d = data as { notifications: NotificationItem[]; unread_count: number };
        setNotifications(d.notifications);
        setUnreadCount(d.unread_count);
        if (d.unread_count > prevUnreadRef.current) {
          const delta = d.unread_count - prevUnreadRef.current;
          setAnnouncement(`${delta} new notification${delta === 1 ? "" : "s"} — ${d.unread_count} unread total`);
        }
        prevUnreadRef.current = d.unread_count;
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const toggleOpen = () => {
    setOpen((prev) => {
      if (!prev) refresh(); // catch up right before showing the panel
      return !prev;
    });
  };

  const handleNotificationClick = async (n: NotificationItem) => {
    setOpen(false);
    if (!n.is_read) {
      setNotifications((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
      setUnreadCount((prev) => Math.max(0, prev - 1));
      notificationsApi.markRead(n.id).catch(() => {});
    }
    if (n.link) router.push(n.link);
  };

  const handleMarkAllRead = async () => {
    setLoading(true);
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    setUnreadCount(0);
    try {
      await notificationsApi.markAllRead();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <span className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</span>
      <button
        type="button"
        onClick={toggleOpen}
        className="relative text-surface-300 hover:text-white transition-colors p-2 -mr-1"
        aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : "Notifications"}
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute top-0.5 right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center leading-none">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 max-w-[90vw] bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl overflow-hidden z-50">
          <div className="px-4 py-3 border-b border-surface-700 flex items-center justify-between">
            <h2 className="text-sm font-bold text-white">Notifications</h2>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                disabled={loading}
                className="inline-flex items-center gap-1 text-[11px] text-gold-400 hover:text-gold-300 transition-colors disabled:opacity-50"
              >
                <CheckCheck className="w-3 h-3" />
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto divide-y divide-surface-700/50">
            {notifications.length === 0 ? (
              <div className="p-6 text-center text-surface-500 text-sm">
                Nothing yet. Trade and waiver updates show up here.
              </div>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleNotificationClick(n)}
                  className={`w-full text-left px-4 py-3 hover:bg-surface-700/40 transition-colors flex items-start gap-2 ${
                    !n.is_read ? "bg-gold-400/5" : ""
                  }`}
                >
                  {!n.is_read && <span className="w-1.5 h-1.5 rounded-full bg-gold-400 mt-1.5 shrink-0" />}
                  <div className={`min-w-0 ${n.is_read ? "ml-3.5" : ""}`}>
                    <p className={`text-xs leading-snug ${n.is_read ? "text-surface-400" : "text-surface-200"}`}>
                      {n.message}
                    </p>
                    <span className="text-[10px] text-surface-500">{timeAgo(n.created_at)}</span>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
