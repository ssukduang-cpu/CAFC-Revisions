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
    <div className="h-screen w-full bg-background overflow-hidden flex flex-col">
      {/* Header */}
      <header className="h-14 border-b bg-card flex items-center justify-between px-4 shrink-0 z-10">
        <div className="flex items-center gap-3">
          <Button 
            variant="ghost" 
            size="icon" 
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="text-muted-foreground hover:text-foreground hidden md:flex h-8 w-8"
          >
            {isSidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          </Button>
          <div className="flex items-center gap-2">
            <div className="bg-primary/10 p-1.5 rounded-md">
              <Scale className="h-5 w-5 text-primary" />
            </div>
            <h1 className="font-serif font-bold text-lg tracking-tight text-foreground">CAFC Opinion Assistant</h1>
            <span className="bg-muted text-muted-foreground text-[10px] px-1.5 py-0.5 rounded-full font-mono uppercase tracking-wider">Precedential Only</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => setIsSourcesOpen(!isSourcesOpen)}
            className="text-muted-foreground hover:text-foreground hidden md:flex"
          >
            {isSourcesOpen ? <PanelRightClose className="h-4 w-4 mr-2" /> : <PanelRightOpen className="h-4 w-4 mr-2" />}
            {isSourcesOpen ? "Hide Sources" : "Show Sources"}
          </Button>
        </div>
      </header>

      <div className="flex-1 overflow-hidden">
        <ResizablePanelGroup direction="horizontal">
          
          {/* Left Sidebar */}
          {isSidebarOpen && (
            <>
              <ResizablePanel defaultSize={20} minSize={15} maxSize={30} className="bg-sidebar/5 border-r hidden md:block">
                {sidebar}
              </ResizablePanel>
              <ResizableHandle className="hidden md:flex" />
            </>
          )}

          {/* Main Chat Area */}
          <ResizablePanel defaultSize={50} minSize={30}>
            {chat}
          </ResizablePanel>

          {/* Right Sources Panel */}
          {isSourcesOpen && (
            <>
              <ResizableHandle />
              <ResizablePanel defaultSize={30} minSize={20} maxSize={45} className="bg-background border-l">
                {sources}
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
