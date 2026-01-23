import { createContext, useContext, useState, ReactNode } from "react";
import type { Citation } from "@/lib/api";

interface AppContextType {
  currentConversationId: string | null;
  setCurrentConversationId: (id: string | null) => void;
  selectedCitations: Citation[];
  setSelectedCitations: (citations: Citation[]) => void;
  showOpinionLibrary: boolean;
  setShowOpinionLibrary: (show: boolean) => void;
  sourcePanelOpen: boolean;
  setSourcePanelOpen: (open: boolean) => void;
  mobileSidebarOpen: boolean;
  setMobileSidebarOpen: (open: boolean) => void;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [selectedCitations, setSelectedCitations] = useState<Citation[]>([]);
  const [showOpinionLibrary, setShowOpinionLibrary] = useState(false);
  const [sourcePanelOpen, setSourcePanelOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <AppContext.Provider 
      value={{
        currentConversationId,
        setCurrentConversationId,
        selectedCitations,
        setSelectedCitations,
        showOpinionLibrary,
        setShowOpinionLibrary,
        sourcePanelOpen,
        setSourcePanelOpen,
        mobileSidebarOpen,
        setMobileSidebarOpen,
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
