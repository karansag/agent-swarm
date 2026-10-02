import { useEffect, useState } from "preact/hooks";

export const COMPACT_LAYOUT = "(max-width: 1000px), (max-width: 1200px) and (pointer: coarse)";

// React to rotation/resizing as well as the initial viewport.
export function useMedia(query) {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const media = matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}
