import { createContext, useContext, useState, ReactNode } from "react";
import type { Citation, ControllingAuthority } from "@/lib/api";

interface AppContextType {
  currentConversationId: string | null;
  setCurrentConversationId: (id: string | null) => void;
  selectedCitations: Citation[];
  setSelectedCitations: (citations: Citation[]) => void;
  controllingAuthorities: ControllingAuthority[];
  setControllingAuthorities: (authorities: ControllingAuthority[]) => void;
  showOpinionLibrary: boolean;
  setShowOpinionLibrary: (show: boolean) => void;
  sourcePanelOpen: boolean;
  setSourcePanelOpen: (open: boolean) => void;
  mobileSidebarOpen: boolean;
  setMobileSidebarOpen: (open: boolean) => void;
  attorneyMode: boolean;
  setAttorneyMode: (mode: boolean) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [selectedCitations, setSelectedCitations] = useState<Citation[]>([]);
  const [controllingAuthorities, setControllingAuthorities] = useState<ControllingAuthority[]>([]);
  const [showOpinionLibrary, setShowOpinionLibrary] = useState(false);
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [attorneyMode, setAttorneyMode] = useState(false); // Default OFF; optional stricter verification filtering

  return (
    <AppContext.Provider 
      value={{
        currentConversationId,
        setCurrentConversationId,
        selectedCitations,
        setSelectedCitations,
        controllingAuthorities,
        setControllingAuthorities,
        showOpinionLibrary,
        setShowOpinionLibrary,
        sourcePanelOpen,
        setSourcePanelOpen,
        mobileSidebarOpen,
        setMobileSidebarOpen,
        attorneyMode,
        setAttorneyMode,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useApp must be used within an AppProvider");
  }
  return context;
}
