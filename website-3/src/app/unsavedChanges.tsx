import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

interface UnsavedChangesContextValue {
  hasUnsavedChanges: boolean;
  registerUnsavedChanges: (dirty: boolean, discard?: () => void) => void;
  discardUnsavedChanges: () => void;
}

const UnsavedChangesContext = createContext<UnsavedChangesContextValue | null>(null);

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const discardRef = useRef<(() => void) | null>(null);

  const registerUnsavedChanges = useCallback((dirty: boolean, discard?: () => void) => {
    discardRef.current = dirty && discard ? discard : null;
    setHasUnsavedChanges(dirty);
  }, []);

  const discardUnsavedChanges = useCallback(() => {
    discardRef.current?.();
    discardRef.current = null;
    setHasUnsavedChanges(false);
  }, []);

  const value = useMemo(
    () => ({ hasUnsavedChanges, registerUnsavedChanges, discardUnsavedChanges }),
    [discardUnsavedChanges, hasUnsavedChanges, registerUnsavedChanges],
  );

  return <UnsavedChangesContext.Provider value={value}>{children}</UnsavedChangesContext.Provider>;
}

export function useUnsavedChanges() {
  const value = useContext(UnsavedChangesContext);
  if (!value) throw new Error("useUnsavedChanges must be used inside UnsavedChangesProvider.");
  return value;
}
