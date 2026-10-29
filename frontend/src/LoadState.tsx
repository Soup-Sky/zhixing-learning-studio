import { LoaderCircle, RotateCcw } from "lucide-react";

// Shared loading / failed-to-load state, so a failed request never looks like an endless spinner.
export default function LoadState({ error, onRetry, label = "正在读取" }: { error?: string; onRetry?: () => void; label?: string }) {
  if (!error)
    return (
      <p className="load-state" role="status">
        <LoaderCircle className="spin" size={18} /> {label}
      </p>
    );
  return (
    <div className="load-state failure" role="alert">
      <p>读取失败：{error}</p>
      {onRetry && (
        <button className="secondary small" onClick={onRetry}>
          <RotateCcw size={15} /> 重试
        </button>
      )}
    </div>
  );
}
