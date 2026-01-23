import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Menu, BookOpen, PanelRightClose, Scale, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MainLayoutProps {
  sidebar: React.ReactNode;
  chat: React.ReactNode;
  sources: React.ReactNode;
}

export function MainLayout({ sidebar, chat, sources }: MainLayoutProps) {
  const [isSourcesOpen, setIsSourcesOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  return (
    <div className="h-screen w-full bg-background overflow-hidden flex flex-col">
      
      <div className="flex-1 overflow-hidden flex">
        <ResizablePanelGroup direction="horizontal">
          
          {isSidebarOpen && (
            <>
              <ResizablePanel defaultSize={18} minSize={15} maxSize={25} className="hidden md:block">
                <div className="h-full bg-sidebar">
                  {sidebar}
                </div>
              </ResizablePanel>
              <ResizableHandle className="hidden md:flex w-px bg-border/30 hover:bg-primary/50 transition-colors" />
            </>
          )}

          <ResizablePanel defaultSize={isSourcesOpen ? 57 : 82} minSize={40}>
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
                  onClick={() => setIsSourcesOpen(!isSourcesOpen)}
                  className="text-muted-foreground hover:text-foreground h-8 w-8 hover:bg-muted/50"
                  data-testid="button-toggle-sources"
                >
                  {isSourcesOpen ? <PanelRightClose className="h-4 w-4" /> : <BookOpen className="h-4 w-4" />}
                </Button>
              </div>
              
              <div className="flex-1 overflow-hidden">
                {chat}
              </div>
            </div>
          </ResizablePanel>

          {isSourcesOpen && (
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

      <header className="h-14 border-t bg-sidebar flex md:hidden items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="bg-primary/10 p-1.5 rounded-md">
            <Scale className="h-4 w-4 text-primary" />
          </div>
          <span className="font-semibold text-sm text-sidebar-foreground">CAFC Copilot</span>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" className="text-sidebar-foreground h-9 w-9">
            <BookOpen className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="text-sidebar-foreground h-9 w-9">
            <Menu className="h-5 w-5" />
          </Button>
        </div>
      </header>
    </div>
  );
}
