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
  const [isSourcesOpen, setIsSourcesOpen] = useState(false); // Default closed in this layout
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  return (
    <div className="h-screen w-full bg-background overflow-hidden flex flex-col md:flex-row">
      
      {/* Mobile Header (Only visible on small screens) */}
      <header className="h-14 border-b bg-sidebar flex md:hidden items-center justify-between px-4 shrink-0 z-10 text-sidebar-foreground">
        <div className="flex items-center gap-2">
          <div className="bg-white/10 p-1 rounded-md">
            <Scale className="h-4 w-4 text-foreground" />
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
              <ResizablePanel defaultSize={20} minSize={15} maxSize={25} className="bg-sidebar border-r border-white/5 hidden md:block">
                {sidebar}
              </ResizablePanel>
              <ResizableHandle className="hidden md:flex bg-background border-r border-white/5" />
            </>
          )}

          {/* Main Chat Area */}
          <ResizablePanel defaultSize={80} minSize={30}>
             <div className="h-full flex flex-col bg-background">
                {/* Desktop Toolbar - Minimalist */}
                <header className="h-12 flex items-center justify-between px-4 shrink-0 z-10 absolute top-0 left-0 right-0 pointer-events-none">
                    <div className="flex items-center gap-2 pointer-events-auto mt-2">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
                        className="text-muted-foreground hover:text-foreground h-8 w-8 hover:bg-white/5"
                      >
                        {isSidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
                      </Button>
                    </div>
                    
                    <div className="flex items-center gap-2 pointer-events-auto mt-2">
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={() => setIsSourcesOpen(!isSourcesOpen)}
                        className="text-muted-foreground hover:text-foreground h-8 w-8 hover:bg-white/5"
                      >
                        {isSourcesOpen ? <PanelRightClose className="h-4 w-4" /> : <BookOpen className="h-4 w-4" />}
                      </Button>
                    </div>
                </header>
                <div className="flex-1 overflow-hidden pt-8">
                   {chat}
                </div>
             </div>
          </ResizablePanel>

          {/* Right Sources Panel (Hidden by default in this view, maybe overlays or pushes) */}
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
