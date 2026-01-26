import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface SearchFiltersProps {
  author: string;
  setAuthor: (value: string) => void;
  includeR36: boolean;
  setIncludeR36: (value: boolean) => void;
}

const JUDGES = [
  { value: "", label: "All Judges" },
  { value: "Newman", label: "Newman" },
  { value: "Lourie", label: "Lourie" },
  { value: "Dyk", label: "Dyk" },
  { value: "Prost", label: "Prost" },
  { value: "Moore", label: "Moore" },
  { value: "Chen", label: "Chen" },
  { value: "Taranto", label: "Taranto" },
  { value: "Hughes", label: "Hughes" },
  { value: "Stoll", label: "Stoll" },
  { value: "Cunningham", label: "Cunningham" },
];

export function SearchFilters({ 
  author, 
  setAuthor, 
  includeR36, 
  setIncludeR36 
}: SearchFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-4 p-3 bg-muted/50 rounded-lg mb-4">
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs font-medium text-muted-foreground">
          Authoring Judge
        </Label>
        <Select value={author} onValueChange={setAuthor}>
          <SelectTrigger 
            className="w-[160px] h-8 text-sm"
            data-testid="select-author-judge"
          >
            <SelectValue placeholder="All Judges" />
          </SelectTrigger>
          <SelectContent>
            {JUDGES.map((judge) => (
              <SelectItem 
                key={judge.value} 
                value={judge.value || "all"}
                data-testid={`option-judge-${judge.value || 'all'}`}
              >
                {judge.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2 ml-auto">
        <Checkbox
          id="include-r36"
          checked={includeR36}
          onCheckedChange={(checked) => setIncludeR36(checked === true)}
          data-testid="checkbox-include-r36"
        />
        <Label 
          htmlFor="include-r36" 
          className="text-sm font-medium cursor-pointer"
        >
          Include Rule 36 Affirmances
        </Label>
      </div>
    </div>
  );
}
