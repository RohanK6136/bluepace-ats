import { useEffect, useState } from "react";

/**
 * Returns the current epoch time and refreshes it once a minute.
 * The first value is populated asynchronously so render stays pure.
 */
export default function useCurrentTime(refreshIntervalMs = 60_000) {
  const [now, setNow] = useState(null);

  useEffect(() => {
    const update = () => setNow(Date.now());
    const initialTimeout = window.setTimeout(update, 0);
    const interval = window.setInterval(update, refreshIntervalMs);

    return () => {
      window.clearTimeout(initialTimeout);
      window.clearInterval(interval);
    };
  }, [refreshIntervalMs]);

  return now;
}
