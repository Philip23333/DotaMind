"use client";

import { siDota2 } from "simple-icons";
import { useCallback, useEffect, useState } from "react";

export function StartupOverlay() {
  const [visible, setVisible] = useState(true);
  const [leaving, setLeaving] = useState(false);

  const dismiss = useCallback(() => {
    setLeaving(true);
    window.setTimeout(() => setVisible(false), 260);
  }, []);

  useEffect(() => {
    const delay = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1400;
    const timer = window.setTimeout(dismiss, delay);
    return () => window.clearTimeout(timer);
  }, [dismiss]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dismiss]);

  if (!visible) return null;

  return (
    <section
      aria-label="DotaMind 正在启动"
      className={`startup-overlay${leaving ? " startup-overlay--leaving" : ""}`}
    >
      <div className="startup-overlay__content">
        <div className="startup-icon" aria-hidden="true">
          <div className="startup-icon__badge">
            <svg aria-hidden="true" role="img" viewBox="0 0 24 24">
              <path d={siDota2.path} />
            </svg>
          </div>
        </div>
        <h1 className="startup-overlay__title">DotaMind</h1>
        <span className="startup-overlay__progress" aria-hidden="true" />
      </div>
    </section>
  );
}
