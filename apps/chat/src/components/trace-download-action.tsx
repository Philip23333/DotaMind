"use client";

import { Button } from "@/components/ui/button";
import { FootprintsIcon, LoaderCircleIcon } from "lucide-react";
import { useRef, useState, type FC } from "react";

import { downloadTrace, TraceExpiredError } from "@/lib/trace-download";

export const TraceDownloadAction: FC<{
  browserId: string;
  traceId: string;
  showLabel?: boolean;
}> = ({ browserId, traceId, showLabel = false }) => {
  const [expired, setExpired] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const downloadInProgress = useRef(false);

  const download = async () => {
    if (downloadInProgress.current || expired) return;
    downloadInProgress.current = true;
    setDownloading(true);
    setError(null);
    try {
      await downloadTrace(browserId, traceId);
    } catch (cause) {
      if (cause instanceof TraceExpiredError) setExpired(true);
      else setError("下载失败，请重试。");
    } finally {
      downloadInProgress.current = false;
      setDownloading(false);
    }
  };

  const label = expired ? "Trace 已过期" : downloading ? "正在下载" : "下载 Trace";
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button
        variant={showLabel ? "outline" : "ghost"}
        size={showLabel ? "sm" : "icon"}
        className={showLabel ? undefined : "size-8"}
        aria-label={label}
        title={label}
        aria-busy={downloading}
        disabled={expired || downloading}
        onClick={() => void download()}
      >
        {downloading ? (
          <LoaderCircleIcon className="size-4 animate-spin" />
        ) : (
          <FootprintsIcon className="size-4" />
        )}
        {showLabel && (expired ? "已过期" : downloading ? "下载中" : "下载")}
      </Button>
      {expired && <span className="text-xs text-muted-foreground">Trace 已过期</span>}
      {error && (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      )}
    </span>
  );
};
