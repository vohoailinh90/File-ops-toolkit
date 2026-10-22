import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Sinh id ngẫu nhiên cho dữ liệu phía client.
 *
 * `crypto.randomUUID()` chỉ tồn tại trong secure context (https hoặc localhost).
 * App nội bộ hay được mở qua `http://<LAN-IP>` từ máy/điện thoại khác, lúc đó
 * `randomUUID` là `undefined` — nên phải có fallback. `getRandomValues()` thì
 * vẫn dùng được ngoài secure context.
 */
export function createId() {
  if (typeof crypto !== "undefined") {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID()
    if (typeof crypto.getRandomValues === "function") {
      const bytes = crypto.getRandomValues(new Uint8Array(16))
      return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
    }
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
