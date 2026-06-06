"use client";

import { PageHeader } from "@/components/brand/page-header";
import { DocumentBrowser } from "@/components/regulatory/document-browser";
import { TemporalSearch } from "@/components/regulatory/temporal-search";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const RegulatoryContent = () => (
  <div className="space-y-6">
    <PageHeader
      kicker="The corpus"
      title="Regulatory explorer"
      description="Ask what law was in force on any date — semantic search over the confirmed gazette corpus, temporally filtered."
    />

    <Tabs defaultValue="search">
      <TabsList>
        <TabsTrigger value="search">Temporal search</TabsTrigger>
        <TabsTrigger value="browse">Browse documents</TabsTrigger>
      </TabsList>
      <TabsContent value="search" className="mt-4">
        <TemporalSearch />
      </TabsContent>
      <TabsContent value="browse" className="mt-4">
        <DocumentBrowser />
      </TabsContent>
    </Tabs>
  </div>
);
