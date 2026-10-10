import Foundation

public struct RustWorkspaceFormulation: Sendable {
    public let classification: FormulationClass
    public let derived: DerivedInstants?
    public let thirdStall: Bool
    public let extensionInstants: DerivedInstants?
    public let parkedAfterDays: Int?
    public let unavailableLocalFacts: [String]

    public init(classification: FormulationClass, derived: DerivedInstants?, thirdStall: Bool,
                extensionInstants: DerivedInstants?, parkedAfterDays: Int?, unavailableLocalFacts: [String] = []) {
        self.classification = classification
        self.derived = derived
        self.thirdStall = thirdStall
        self.extensionInstants = extensionInstants
        self.parkedAfterDays = parkedAfterDays
        self.unavailableLocalFacts = unavailableLocalFacts
    }
}

public struct RustWorkspaceReviewSummary: Sendable {
    public let entryNotice: ReviewEntryNotice?
    public let explainerNeeded: Bool
    public let daysSinceLastReview: Int?
    public let decisionStep: DecisionStepOutcome?
}

public struct RustWorkspaceReviewState: Sendable {
    public let settings: ReviewSettings
    public let server: ReviewServerFacts
    public let openSession: ReviewSession?
    public let unseenParks: [ParkAck]
    public let unseenParkTotal: Int
    public let askCount: Int
    public let receipts: [RustWorkspaceReviewReceipt]
}

public struct RustWorkspaceReviewReceipt: Sendable {
    public let taskID: TaskID
    public let kind: ReceiptKind
    public let hiddenUntil: Date
    public let taskRevision: Int
}

public struct RustWorkspaceReviewQueue: Sendable {
    public let tasks: [TaskRecord]
    public let capacity: CapacityMirror?
    public let somedayTotal: Int?
    public let winsTotal: Int?
    public let dueDays: [DueDay]
}

extension RustDomainFacade {
    public func workspaceReviewState(from result: Data, keeping previous: GTDState, at date: Date) throws -> RustWorkspaceReviewState {
        let value = try RustJSON.object(result).object("value")
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        var state = GTDState.empty
        state.review = previous.review
        try applyOwned("review_settings", value: value.object("settings"), to: &state, at: date, ids: ids)
        var open: ReviewSession?
        if let session = value.optionalObject("open_session") {
            try applyOwned("review_session", value: session, to: &state, at: date, ids: ids)
            open = state.review.sessions[ReviewSessionID(ids.swift(try session.string("id")))]
        }
        var last: LastCountedReview?
        if let row = value.optionalObject("last_counted_review") {
            var counts = SessionCounts()
            let rawCounts = try row.object("counts")
            for counter in SessionCounter.allCases { counts[counter] = rawCounts[counter.rawValue] as? Int ?? 0 }
            guard let status = ReviewSessionStatus(rawValue: try row.string("status")),
                  let origin = ReviewOrigin(rawValue: try row.string("origin")) else { throw RustDomainError.malformedResult }
            last = LastCountedReview(sessionID: ReviewSessionID(ids.swift(try row.string("session_id"))),
                status: status, origin: origin, endedAt: try row.optionalInstant("ended_at"), counts: counts,
                clearStart: row.optionalString("clear_start").flatMap { ClearStart(rawValue: $0) })
        }
        let unseen = try value.objects("unseen_parks").map { row in
            ParkAck(taskID: TaskID(ids.swift(try row.string("task_id"))),
                formulationID: FormulationID(ids.swift(try row.string("formulation_id"))),
                parkedAt: try row.instant("parked_at"))
        }
        let receipts = try value.objects("receipts").map { row in
            guard let kind = ReceiptKind(rawValue: try row.string("kind")) else {
                throw RustDomainError.malformedResult
            }
            return RustWorkspaceReviewReceipt(taskID: TaskID(ids.swift(try row.string("task_id"))), kind: kind,
                hiddenUntil: try row.instant("hidden_until"), taskRevision: try row.counter("task_revision"))
        }
        return RustWorkspaceReviewState(settings: state.review.settings,
            server: ReviewServerFacts(exposed: true, lastCountedReviewAt: try value.optionalInstant("last_counted_review_at"),
                lastCountedReview: last, nextReviewAt: try value.optionalInstant("next_review_at"),
                restartMode: try value.bool("restart_mode"), openSessionID: open?.id, pulledAt: date),
            openSession: open, unseenParks: unseen, unseenParkTotal: try value.int("unseen_parks_total"),
            askCount: try value.object("counts").int("asks_for_decision"), receipts: receipts)
    }

    public func workspaceOpenReleasesQuery(_ kind: BulkReleaseKindCode, session: ReviewSessionID? = nil,
                                           bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(bindings: bindings, preservesReferences: true)
        return try RustJSON.data(["kind": "open_releases", "release_kind": kind.rawValue,
                                  "session_id": ids.optional(session?.rawValue, prefix: "review")])
    }

    public func workspaceOpenReleases(from result: Data, keeping previous: GTDState, at date: Date) throws -> [BulkReleaseRecord] {
        let rows = try RustJSON.object(result)["value"] as? [WireObject]
        guard let rows else { throw RustDomainError.malformedResult }
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        var state = previous
        return try rows.map { row in
            try applyOwned("review_bulk_release", value: row, to: &state, at: date, ids: ids)
            guard let record = state.review.bulkReleases[BulkID(ids.swift(try row.string("id")))] else {
                throw RustDomainError.malformedResult
            }
            return record
        }
    }

    public func workspaceReviewQueueQuery(_ step: ReviewStep, session: ReviewSessionID? = nil,
                                         bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(bindings: bindings, preservesReferences: true)
        return try RustJSON.data(["kind": "review_queue", "step": step.rawValue,
                                  "session_id": ids.optional(session?.rawValue, prefix: "review")])
    }

    public func workspaceReviewSummaryQuery(session: ReviewSessionID? = nil, explainerSeenLocally: Bool,
                                           activatedAt: Date?, endedElsewhere: ReviewSessionID? = nil,
                                           bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(bindings: bindings, preservesReferences: true)
        return try RustJSON.data(["kind": "review_summary", "session_id": ids.optional(session?.rawValue, prefix: "review"),
            "local": ["explainer_seen_locally": explainerSeenLocally, "activated_at": wireInstant(activatedAt),
                      "ended_elsewhere_session": ids.optional(endedElsewhere?.rawValue, prefix: "review")]])
    }

    public func workspaceParkReturnQuery(_ task: TaskID, shown: ParkAck? = nil,
                                        bindings: [RustWorkspaceIdentityBinding] = []) throws -> Data {
        var ids = RustIDTable(bindings: bindings, preservesReferences: true)
        var query: WireObject = ["kind": "park_return_shown", "task_id": ids.task(task)]
        if let shown {
            query["parked_at"] = wireInstant(shown.parkedAt)
            query["formulation_id"] = shown.formulationID.rawValue
        }
        return try RustJSON.data(query)
    }

    public func workspaceFormulation(from result: Data) throws -> RustWorkspaceFormulation {
        try workspaceFormulationValue(RustJSON.object(result).object("value"))
    }

    func workspaceFormulationValue(_ value: WireObject) throws -> RustWorkspaceFormulation {
        guard let classification = FormulationClass(rawValue: try value.string("class")) else {
            throw RustDomainError.malformedResult
        }
        func derived(_ row: WireObject) throws -> DerivedInstants {
            DerivedInstants(start: try row.instant("start"), ageingAt: try row.instant("ageing_at"),
                askAt: try row.instant("ask_at"), parkDueAt: try row.instant("park_due_at"),
                tomorrowAt: try row.instant("tomorrow_at"), pausedUntil: try row.optionalInstant("paused_until"))
        }
        return RustWorkspaceFormulation(classification: classification,
            derived: try value.optionalObject("derived").map(derived), thirdStall: try value.bool("third_stall"),
            extensionInstants: try value.optionalObject("extension").map(derived),
            parkedAfterDays: value["parked_after_days"] as? Int,
            unavailableLocalFacts: try value.strings("unavailable_local_facts"))
    }

    public func workspaceParkReturnProblem(from result: Data) throws -> ParkReturnProblem? {
        guard let row = try RustJSON.object(result).optionalObject("value") else { return nil }
        switch try row.string("type") {
        case "changed_elsewhere": return .changedElsewhere
        case "project_archived": return .projectArchived(name: try row.string("name"))
        default: throw RustDomainError.malformedResult
        }
    }

    public func workspaceReviewSummary(from result: Data) throws -> RustWorkspaceReviewSummary {
        let row = try RustJSON.object(result).object("value")
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        var step: DecisionStepOutcome?
        if let value = row.optionalObject("decision_step") {
            switch try value.string("type") {
            case "card": step = .card(TaskID(ids.swift(try value.string("task_id"))),
                position: try value.int("position"), total: try value.int("total"))
            case "nothing_asks": step = .nothingAsks
            case "all_decided": step = .allDecided(try value.int("decided"), keptWording: try value.int("kept_wording"))
            case "some_left": step = .someLeft(decided: try value.int("decided"), total: try value.int("total"),
                stillAsking: try value.int("still_asking"))
            default: throw RustDomainError.malformedResult
            }
        }
        var notice: ReviewEntryNotice?
        if let value = row.optionalObject("entry_notice") {
            switch try value.string("type") {
            case "closed_after_a_week": notice = .closedAfterAWeek(startedAt: try value.instant("started_at"),
                decisions: try value.int("decisions"))
            case "replaced_elsewhere":
                guard let origin = ReviewOrigin(rawValue: try value.string("origin")) else { throw RustDomainError.malformedResult }
                notice = .replacedElsewhere(origin: origin, decisions: try value.int("decisions"))
            default: throw RustDomainError.malformedResult
            }
        }
        return RustWorkspaceReviewSummary(entryNotice: notice, explainerNeeded: try row.bool("explainer_needed"),
            daysSinceLastReview: row["days_since_last_review"] as? Int, decisionStep: step)
    }

    public func workspaceReviewQueue(from result: Data, keeping previous: GTDState, at date: Date) throws -> RustWorkspaceReviewQueue {
        let value = try RustJSON.object(result).object("value")
        let tasks = try workspaceTasks(from: RustJSON.data(value["items"] ?? []), keeping: previous, at: date)
        let meta = try value.object("meta")
        var capacity: CapacityMirror?
        if meta["next_count"] != nil {
            capacity = CapacityMirror(nextCount: try meta.int("next_count"), weeksOfHistory: try meta.int("weeks_of_history"),
                weeklyAverage4w: meta["weekly_average_4w"] as? Double, impliedWeeks: meta["implied_weeks"] as? Double)
        }
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        let byID = Dictionary(uniqueKeysWithValues: tasks.map { ($0.id, $0) })
        let days = try (meta["days"] as? [WireObject] ?? []).map { row -> DueDay in
            guard let day = CalendarDay(isoString: try row.string("day")) else { throw RustDomainError.malformedResult }
            return DueDay(day: day, tasks: try row.strings("task_ids").compactMap { byID[TaskID(ids.swift($0))] })
        }
        return RustWorkspaceReviewQueue(tasks: tasks, capacity: capacity,
            somedayTotal: meta["eligible_total"] as? Int, winsTotal: meta["count"] as? Int, dueDays: days)
    }

    public func workspaceTasks(from result: Data, keeping previous: GTDState, at date: Date) throws -> [TaskRecord] {
        let raw = try JSONSerialization.jsonObject(with: result)
        let values = (raw as? WireObject)?["value"] ?? raw
        guard let rows = values as? [WireObject] else { throw RustDomainError.malformedResult }
        let ids = RustIDTable(stripsUUIDPrefixes: false)
        return try rows.map { row in
            let id = TaskID(ids.swift(try row.string("id")))
            return try workspaceTask(from: RustJSON.data(row), keeping: previous.tasks[id], detail: false, at: date)
        }
    }
}


extension RustDomainFacade {
    public func workspaceReviewQueue(from page: RustWorkspacePage, at date: Date) throws -> RustWorkspaceReviewQueue {
        let value = try workspaceReviewQueue(from: page.result, keeping: .empty, at: date)
        return RustWorkspaceReviewQueue(tasks: try workspaceFramedTasks(value.tasks, from: page, at: date),
            capacity: value.capacity, somedayTotal: value.somedayTotal, winsTotal: value.winsTotal, dueDays: value.dueDays)
    }
}
