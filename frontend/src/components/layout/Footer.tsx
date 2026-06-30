import { FileCode2 } from "lucide-react";
import { Link } from "react-router-dom";

export function Footer() {
  return (
    <footer className="border-t bg-muted/30">
      <div className="container flex flex-col items-center justify-between gap-4 py-6 text-xs text-muted-foreground sm:flex-row">
        <p>
          A portfolio project. Not legal advice.{" "}
          <Link to="/terms" className="underline">
            Read the terms.
          </Link>
        </p>
        <a
          href="https://github.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 hover:text-foreground"
        >
          <FileCode2 className="h-3.5 w-3.5" />
          Source
        </a>
      </div>
    </footer>
  );
}
