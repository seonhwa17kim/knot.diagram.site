(* Compare PD codes as unlabeled combinatorial diagrams. *)

ClearAll[
  parsePDEntry, extractDiagram, edgeGadget, pdGraph, pdEquivalentQ,
  pdStatus, compareFile, oldDir, newDir, outFile, candidateFile, files, rows,
  timeLimit
];

parsePDEntry[s_String] := ToExpression[s];
parsePDEntry[x_List] := x;

extractDiagram[data_Association] := If[
  KeyExistsQ[data, "Diagrams"],
  First[data["Diagrams"]],
  data["Diagram"]
];

edgeGadget[u_, v_, type_String, id_Integer] := Module[
  {mid = {type, id}, pendants},
  pendants = If[type === "strand", {{type, id, 1}}, {{type, id, 1}, {type, id, 2}}];
  Join[
    {UndirectedEdge[u, mid], UndirectedEdge[mid, v]},
    UndirectedEdge[mid, #] & /@ pendants
  ]
];

pdGraph[pd_List] := Module[
  {tuples, labels, n, strandPairs, crossingPairs, strandEdges, crossingEdges},
  tuples = parsePDEntry /@ pd;
  labels = Sort[DeleteDuplicates[Flatten[tuples]]];
  n = Max[labels];
  strandPairs = Table[{{"h", i}, {"h", If[i == n, 1, i + 1]}}, {i, n}];
  crossingPairs = Flatten[
    Table[
      With[{t = tuples[[j]]},
        {{{"h", t[[1]]}, {"h", t[[2]]}},
         {{"h", t[[2]]}, {"h", t[[3]]}},
         {{"h", t[[3]]}, {"h", t[[4]]}},
         {{"h", t[[4]]}, {"h", t[[1]]}}}
      ],
      {j, Length[tuples]}
    ],
    1
  ];
  strandEdges = Flatten[MapIndexed[edgeGadget[#[[1]], #[[2]], "strand", First[#2]] &, strandPairs], 1];
  crossingEdges = Flatten[MapIndexed[edgeGadget[#[[1]], #[[2]], "crossing", First[#2]] &, crossingPairs], 1];
  Graph[Join[strandEdges, crossingEdges]]
];

pdEquivalentQ[oldPD_List, newPD_List] := Quiet @ Check[
  TimeConstrained[IsomorphicGraphQ[pdGraph[oldPD], pdGraph[newPD]], timeLimit, "timeout"],
  False
];

pdStatus[oldPD_List, newPD_List] := Module[{equiv},
  If[oldPD === newPD, Return["exact"]];
  equiv = pdEquivalentQ[oldPD, newPD];
  Which[
    equiv === "timeout", "timeout",
    TrueQ[equiv], "diagram_isomorphic",
    True, "changed"
  ]
];

compareFile[file_String] := Module[
  {old, new, oldDiagram, newDiagram, status},
  old = Import[FileNameJoin[{oldDir, file}], "RawJSON"];
  new = Import[FileNameJoin[{newDir, file}], "RawJSON"];
  oldDiagram = extractDiagram[old];
  newDiagram = extractDiagram[new];
  status = pdStatus[oldDiagram["PDcode"], newDiagram["PDcode"]];
  <|
    "filename" -> file,
    "index" -> new["Index"],
    "name" -> new["Name"],
    "pdcode_wolfram_status" -> status
  |>
];

oldDir = If[Length[$ScriptCommandLine] >= 2, $ScriptCommandLine[[2]], "parabolic/data/json260706"];
newDir = If[Length[$ScriptCommandLine] >= 3, $ScriptCommandLine[[3]], "parabolic/data/json"];
outFile = If[Length[$ScriptCommandLine] >= 4, $ScriptCommandLine[[4]], "reports/parabolic_json_validation/pdcode_wolfram.csv"];
candidateFile = If[Length[$ScriptCommandLine] >= 5, $ScriptCommandLine[[5]], ""];
timeLimit = If[Length[$ScriptCommandLine] >= 6, ToExpression[$ScriptCommandLine[[6]]], 2];

files = If[
  candidateFile =!= "" && FileExistsQ[candidateFile],
  Rest[Import[candidateFile, "CSV"]][[All, 1]],
  FileNameTake /@ FileNames["*.json", oldDir]
];
files = SortBy[files, ToExpression @ StringCases[#, "(" ~~ n : DigitCharacter .. ~~ ").json" :> n][[1]] &];
rows = compareFile /@ files;

Export[outFile, rows, "CSV"];
Print["Wrote ", Length[rows], " rows to ", outFile];
