# Scanning jobs

Incremental, batched scan pipeline. **Only new/changed work is expensive.**

## Design rules

1. **Scan for changes** discovers new model dirs (bounded depth, default `SCAN_MAX_DEPTH=6`) and shallow-checks **known models** for new files. Missing files are handled by `CheckMissingFilesJob` (batched), not a full re-scan loop.
2. **AddNewFiles** only enqueues file metadata/analysis for *newly created* `ModelFile` rows — never re-parses the whole model.
3. **Rescan all models** syncs filesystem + problem checks. It does **not** re-analyse every mesh (`deep: true` is opt-in on `CheckModelJob`).
4. **Analysis** (digest, duplicates, manifold) runs for new files only, or when `deep: true`, or via Phase B `AnalyseUndigestedJob` / `rake manyfold:analyse_undigested`.
5. Scan jobs set explicit `lock_ttl`. Stuck locks: `Scan::Library::DetectFilesystemChangesJob.unlock!` (or `ActiveJob::Uniqueness.unlock!`).

```mermaid
flowchart TD
    DFS[Scan::Library::DetectFilesystemChangesJob]
    CMFP[Scan::Library::CreateModelFromPathJob]
    ANF[Scan::Model::AddNewFilesJob]
    MISS[Scan::Library::CheckMissingFilesJob]
    PM[Scan::Model::ParseMetadataJob]
    PMF[Scan::ModelFile::ParseMetadataJob]
    FIN[Scan::Model::FinalizeScanBatchJob]
    CFP[Scan::Model::CheckForProblemsJob]
    CA[Scan::CheckAllJob]
    CM[Scan::CheckModelJob]
    OM[OrganizeModelJob]
    PUF[ProcessUploadedFileJob]
    AMF[Analysis::AnalyseModelFileJob]
    UND[Scan::AnalyseUndigestedJob]
    FC[Analysis::FileConversionJob]
    GA[Analysis::GeometricAnalysisJob]

    ModelEdit([fa:fa-person Model edited])
    Organize([fa:fa-person Organize button])
    ScanAll([fa:fa-person Scan for changes])
    CheckAll([fa:fa-person Rescan all models])
    MainUpload([fa:fa-person Upload button])
    FileUpload([fa:fa-person Upload files in model])
    FileConvert([fa:fa-person Convert file button])

    ScanAll --> DFS
    DFS -->|new model dirs| CMFP
    DFS -->|new files in known models| ANF
    DFS --> MISS
    MISS -->|light| CFP
    CheckAll --> CA
    CA -->|each model| CM
    CM --> ANF
    CMFP --> ANF
    ANF -->|new files only| PMF
    ANF --> PM
    PM -->|batch| FIN
    FIN --> CFP
    PM -->|no batch| CFP
    ModelEdit --> CFP
    PMF --> AMF
    AMF -->|geometric analysis enabled?| GA
    Organize --> OM
    OM --> CFP
    MainUpload --> PUF
    FileUpload --> PUF
    PUF -->|new model?| ANF
    PUF -->|new file in existing model?| CFP
    PUF -->|new file in existing model?| PMF
    FileConvert --> FC
    FC --> AMF


    classDef queue_analysis fill:#700,stroke:#f00,stroke-width:2px;
    classDef queue_scan fill:#070,stroke:#0f0,stroke-width:2px;
    classDef queue_default fill:#077,stroke:#0ff,stroke-width:2px;
    classDef queue_performance fill:#007,stroke:#00f,stroke-width:2px;

    class DFS,CA,CM,CMFP,ANF,PM,PMF,CFP,FIN,MISS queue_scan
    class FC,GA queue_performance
    class AMF,UND queue_analysis
    class OM,PUF queue_default

    classDef user_action fill:#777,stroke:#fff,stroke-width:2px;
    class ModelEdit,Organize,ScanAll,CheckAll,MainUpload,FileUpload,FileConvert user_action

```

### Queues

* Green: `scan` — filesystem sync, metadata, problems
* Red: `analysis` / `low` — digests and file analysis
* Cyan: `default` — upload / organize
* Blue: `performance` — heavy mesh work (concurrency 1)

Grey ovals are user-initiated actions.
