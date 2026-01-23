export interface Opinion {
  id: string;
  caseName: string;
  appealNo: string;
  date: string;
  status: "Precedential" | "Nonprecedential";
  origin: string; // e.g., "D. Del." or "PTAB"
  summary: string;
  isIngested: boolean;
}

export interface Citation {
  id: string;
  opinionId: string;
  caseName: string;
  page: number;
  text: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  timestamp: string;
}

export const MOCK_OPINIONS: Opinion[] = [
  {
    id: "op-1",
    caseName: "Amgen Inc. v. Sanofi",
    appealNo: "20-1074",
    date: "2021-02-11",
    status: "Precedential",
    origin: "D. Del.",
    summary: "Affirming judgment as a matter of law of lack of enablement of claims directed to antibodies binding to PCSK9.",
    isIngested: true,
  },
  {
    id: "op-2",
    caseName: "Uniloc 2017 LLC v. Hulu, LLC",
    appealNo: "19-1686",
    date: "2020-07-22",
    status: "Precedential",
    origin: "PTAB",
    summary: "Reversing PTAB's decision regarding patent eligibility under Section 101 for claims related to adjusting license delivery.",
    isIngested: true,
  },
  {
    id: "op-3",
    caseName: "Apple Inc. v. Fintiv, Inc.",
    appealNo: "20-1561",
    date: "2021-05-18",
    status: "Precedential",
    origin: "PTAB",
    summary: "Dismissing appeal for lack of jurisdiction over PTAB's decision to deny institution of inter partes review.",
    isIngested: true,
  },
  {
    id: "op-4",
    caseName: "Berkheimer v. HP Inc.",
    appealNo: "17-1437",
    date: "2018-02-08",
    status: "Precedential",
    origin: "N.D. Ill.",
    summary: "Holding that whether a claim element represents well-understood, routine, and conventional activity is a question of fact.",
    isIngested: false,
  },
  {
    id: "op-5",
    caseName: "Vanda Pharm. v. West-Ward Pharm.",
    appealNo: "16-2707",
    date: "2018-04-13",
    status: "Precedential",
    origin: "D. Del.",
    summary: "Affirming that claims directed to a method of treatment using iloperidone were patent eligible under Section 101.",
    isIngested: false,
  }
];

export const MOCK_CHAT_HISTORY: Message[] = [
  {
    id: "msg-1",
    role: "user",
    content: "What is the current standard for enablement of antibody claims?",
    timestamp: "10:30 AM"
  },
  {
    id: "msg-2",
    role: "assistant",
    content: "Under the current Federal Circuit jurisprudence, particularly following *Amgen Inc. v. Sanofi*, antibody claims defined by function (binding to a specific antigen) rather than structure must satisfy the full scope of the enablement requirement. The Court has rejected the 'newly characterized antigen' test.\n\nThe specification must enable the full scope of the claimed invention without undue experimentation. For functional claims covering a genus of antibodies, this often requires disclosing a representative number of species or structural features common to the genus.",
    timestamp: "10:31 AM",
    citations: [
      {
        id: "cit-1",
        opinionId: "op-1",
        caseName: "Amgen Inc. v. Sanofi",
        page: 12,
        text: "The functional definition of the claims at issue—binding to PCSK9 and blocking binding to LDL-R—covers a vast scope of potential antibodies. The specification here did not enable the full scope of these claims because it failed to teach how to make and use the full range of claimed candidates without undue experimentation."
      },
      {
        id: "cit-2",
        opinionId: "op-1",
        caseName: "Amgen Inc. v. Sanofi",
        page: 14,
        text: "We therefore reaffirm that the enablement inquiry for claims that include functional requirements is no different from the inquiry for other types of claims: the specification must enable the full scope of the invention as defined by its claims."
      }
    ]
  }
];
