import { useCallback, useEffect, useState } from 'react';

import { flicksApi } from '../../api/flicks';
import type { Progress } from '../../api/types';

/** Watch progress, most recent first. Call `refresh` after the player saves. */
export function useHistory() {
  const [items, setItems] = useState<Progress[]>([]);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let current = true;
    flicksApi.history().then(
      response => {
        if (current) setItems(response.items);
      },
      () => {
        // History is a convenience; a failure must not break browsing. The next refresh retries.
      },
    );
    return () => {
      current = false;
    };
  }, [version]);
  const refresh = useCallback(() => setVersion(v => v + 1), []);
  return { items, refresh };
}
