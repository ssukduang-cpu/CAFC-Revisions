import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Menu, BookOpen, PanelRightClose, Scale, PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";

interface MainLayoutProps {
  sidebar: React.ReactNode;
  chat: React.ReactNode;
  sources: React.ReactNode;
}

export function MainLayout({ sidebar, chat, sources }: MainLayoutProps) {
  const { sourcePanelOpen, setSourcePanelOpen, mobileSidebarOpen, setMobileSidebarOpen } = useApp();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  return (
    <div className="h-screen w-full bg-background overflow-hidden flex flex-col">
      
      <div className="flex-1 overflow-hidden flex">
        <ResizablePanelGroup direction="horizontal">
          
          {isSidebarOpen && (
            <>
              <ResizablePanel defaultSize={20} minSize={18} maxSize={30} className="hidden md:block">
                <div className="h-full bg-sidebar">
                  {sidebar}
                </div>
              </ResizablePanel>
              <ResizableHandle className="hidden md:flex w-px bg-border/30 hover:bg-primary/50 transition-colors" />
            </>
          )}

          <ResizablePanel defaultSize={sourcePanelOpen ? 57 : 82} minSize={40}>
            <div className="h-full flex flex-col bg-background relative">
              <div className="absolute top-3 left-3 z-10 hidden md:flex">
                <Button 
                  variant="ghost" 
                  size="icon" 
                  onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                  className="text-muted-foreground hover:text-foreground h-8 w-8 hover:bg-muted/50"
                  data-testid="button-toggle-sidebar"
                >
                  {isSidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
                </Button>
              </div>
              
              <div className="absolute top-3 right-3 z-10 hidden md:flex">
                <Button 
                  variant="ghost" 
                  size="icon" 
                  onClick={() => setSourcePanelOpen(!sourcePanelOpen)}
                  className="text-muted-foreground hover:text-foreground h-8 w-8 hover:bg-muted/50"
                  data-testid="button-toggle-sources"
                >
                  {sourcePanelOpen ? <PanelRightClose className="h-4 w-4" /> : <BookOpen className="h-4 w-4" />}
                </Button>
              </div>
              
              <div className="flex-1 overflow-hidden">
                {chat}
              </div>
            </div>
          </ResizablePanel>

          {sourcePanelOpen && (
            <>
              <ResizableHandle className="w-px bg-border/30 hover:bg-primary/50 transition-colors" />
              <ResizablePanel defaultSize={25} minSize={20} maxSize={35}>
                <div className="h-full bg-card border-l border-border/30">
                  {sources}
                </div>
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>
      </div>

      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div 
            className="absolute inset-0 bg-black/50" 
            onClick={() => setMobileSidebarOpen(false)}
          />
          <div className="absolute left-0 top-0 bottom-0 w-72 bg-sidebar shadow-xl animate-in slide-in-from-left duration-200">
            <div className="absolute top-3 right-3">
              <Button 
                variant="ghost" 
                size="icon" 
                onClick={() => setMobileSidebarOpen(false)}
                className="h-8 w-8 text-sidebar-foreground"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
            {sidebar}
          </div>
        </div>
      )}

      <header className="h-14 border-t border-sidebar-border bg-sidebar flex md:hidden items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="bg-sidebar-primary p-1.5 rounded-lg">
            <Scale className="h-4 w-4 text-sidebar-primary-foreground" />
          </div>
          <span className="font-bold text-sm text-sidebar-foreground">Federal Circuit AI</span>
        </div>
        <div className="flex gap-1">
          <Button 
            variant="ghost" 
            size="icon" 
            className="text-sidebar-foreground h-9 w-9"
            onClick={() => setSourcePanelOpen(!sourcePanelOpen)}
            data-testid="button-mobile-sources"
          >
            <BookOpen className="h-4 w-4" />
          </Button>
          <Button 
            variant="ghost" 
            size="icon" 
            className="text-sidebar-foreground h-9 w-9"
            onClick={() => setMobileSidebarOpen(true)}
            data-testid="button-mobile-menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </div>
      </header>
    </div>
  );
}
