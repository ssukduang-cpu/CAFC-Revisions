import { MainLayout } from "@/components/layout/MainLayout";
import { Sidebar } from "@/components/Sidebar";
import { ChatInterface } from "@/components/ChatInterface";
import { SourcesPanel } from "@/components/SourcesPanel";

export default function Home() {
  return (
    <MainLayout
      sidebar={<Sidebar />}
      chat={<ChatInterface />}
      sources={<SourcesPanel />}
    />
  );
}
