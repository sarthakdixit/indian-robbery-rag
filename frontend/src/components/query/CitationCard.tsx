import { ChevronDown, ChevronRight, ExternalLink, FileText } from "lucide-react";
import type { Citation } from "@/api/schemas/citation";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useCitationExpansionStore } from "@/stores/useCitationExpansionStore";
import { cn } from "@/lib/utils";

type CitationCardProps = {
  citation: Citation;
};

/**
 * One citation row. Header shows the index, source type chip, and
 * citation reference (e.g. "BNS §309" or "State v. Doe (2021) Bombay HC").
 * Body expands to show the chunk excerpt and "View source" links.
 */
export function CitationCard({ citation }: CitationCardProps) {
  const isExpanded = useCitationExpansionStore((s) => s.expanded.has(citation.index));
  const toggle = useCitationExpansionStore((s) => s.toggle);

  const courtYearLabel =
    citation.court !== null && citation.year !== null
      ? `${citation.court} (${citation.year.toString()})`
      : null;

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={() => {
          toggle(citation.index);
        }}
        className={cn(
          "flex w-full items-center gap-3 p-4 text-left",
          "hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
        )}
        aria-expanded={isExpanded}
        aria-controls={`citation-body-${citation.index.toString()}`}
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        )}

        <span className="font-mono text-sm text-muted-foreground">[{citation.index}]</span>

        <Badge variant={citation.source_type === "act" ? "default" : "secondary"}>
          {citation.source_type === "act" ? "Act" : "Case"}
        </Badge>

        <span className="flex-1 truncate font-medium">{citation.citation}</span>

        {courtYearLabel !== null && (
          <span className="hidden text-sm text-muted-foreground sm:inline">{courtYearLabel}</span>
        )}
      </button>

      {isExpanded && (
        <div id={`citation-body-${citation.index.toString()}`} className="border-t bg-muted/30 p-4">
          <blockquote className="border-l-4 border-primary/30 pl-4 text-sm italic text-foreground/90">
            {citation.excerpt}
          </blockquote>

          <div className="mt-4 flex flex-wrap gap-2">
            {citation.source_url !== null && (
              <Button asChild size="sm" variant="outline">
                <a href={citation.source_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-3.5 w-3.5" />
                  View source
                </a>
              </Button>
            )}
            {citation.pdf_url !== null && (
              <Button asChild size="sm" variant="outline">
                <a href={citation.pdf_url} target="_blank" rel="noopener noreferrer">
                  <FileText className="h-3.5 w-3.5" />
                  PDF
                </a>
              </Button>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
