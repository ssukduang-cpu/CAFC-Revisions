import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Menu, BookOpen, MessageSquare, PanelRightClose, PanelRightOpen, Scale, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MainLayoutProps {
  sidebar: React.ReactNode;
  chat: React.ReactNode;
  sources: React.ReactNode;
}

export function MainLayout({ sidebar, chat, sources }: MainLayoutProps) {
  const [isSourcesOpen, setIsSourcesOpen] = useState(true);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  return (
    <div className="h-screen w-full bg-background overflow-hidden flex flex-col md:flex-row">
      
      {/* Mobile Header (Only visible on small screens) */}
      <header className="h-14 border-b bg-sidebar flex md:hidden items-center justify-between px-4 shrink-0 z-10 text-sidebar-foreground">
        <div className="flex items-center gap-2">
          <div className="bg-primary/20 p-1 rounded-md">
            <Scale className="h-4 w-4 text-primary" />
          </div>
          <span className="font-semibold text-sm">CAFC Assistant</span>
        </div>
        <Button variant="ghost" size="icon" className="text-sidebar-foreground">
          <Menu className="h-5 w-5" />
        </Button>
      </header>

      <div className="flex-1 overflow-hidden h-full">
        <ResizablePanelGroup direction="horizontal">
          
          {/* Left Sidebar */}
          {isSidebarOpen && (
            <>
              <ResizablePanel defaultSize={20} minSize={15} maxSize={25} className="bg-sidebar border-r hidden md:block">
                {sidebar}
              </ResizablePanel>
              <ResizableHandle className="hidden md:flex bg-border/50" />
            </>
          )}

          {/* Main Chat Area */}
          <ResizablePanel defaultSize={55} minSize={30}>
             <div className="h-full flex flex-col">
                {/* Desktop Header/Toolbar */}
                <header className="h-14 border-b bg-background flex items-center justify-between px-4 shrink-0 z-10">
                    <div className="flex items-center gap-2">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                        className="text-muted-foreground hover:text-foreground hidden md:flex h-8 w-8"
                      >
                        {isSidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
                      </Button>
                      <span className="font-semibold text-sm text-foreground/80">Enablement of antibody claims</span>
                    </div>
                    
                    <div className="flex items-center gap-2">
                      <Button 
                        variant="ghost" 
                        size="sm" 
                        onClick={() => setIsSourcesOpen(!isSourcesOpen)}
                        className={cn(
                          "text-muted-foreground hover:text-foreground hidden md:flex transition-colors",
                          isSourcesOpen && "bg-muted/50 text-foreground"
                        )}
                      >
                        {isSourcesOpen ? <PanelRightClose className="h-4 w-4 mr-2" /> : <PanelRightOpen className="h-4 w-4 mr-2" />}
                        Sources
                      </Button>
                    </div>
                </header>
                <div className="flex-1 overflow-hidden">
                   {chat}
                </div>
             </div>
          </ResizablePanel>

          {/* Right Sources Panel */}
          {isSourcesOpen && (
            <>
              <ResizableHandle className="bg-border/50" />
              <ResizablePanel defaultSize={25} minSize={20} maxSize={40} className="bg-background border-l">
                {sources}
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
