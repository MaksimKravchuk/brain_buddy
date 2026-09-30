import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// Projects and tags (`TaskService.create_project` … `delete_tag`).
extension ServerState {
    // MARK: - Projects

    func listProjects(_ owner: String) -> Reply {
        let data = data(owner)
        let active = data.projects.values.filter { $0.state == .active }
            .sorted { (PythonText.strip($0.name).lowercased(), $0.id) < (PythonText.strip($1.name).lowercased(), $1.id) }
        return .json(200, active.map(data.projectDTO))
    }

    func getProject(_ id: String, owner: String) throws(FakeHTTPError) -> Reply {
        let data = data(owner)
        return .json(200, data.projectDTO(try data.project(id)))
    }

    mutating func createProject(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["name", "color"])
        let rawName = try body.string("name", required: true, min: 1, max: GTDLimits.name) ?? ""
        let color = try body.string("color", max: GTDLimits.color)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "create_project"
        let fingerprint = body.fingerprint(command: command)
        if case .project(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(201, data.projectDTO(stored))
        }
        let name = NameNormalizer.display(rawName)
        guard !name.isEmpty else { throw .validation(["body", "name"], "String should have at least 1 character") }
        let project = ProjectRow(
            id: mint("project"), name: name, normalizedName: NameNormalizer.project(name), color: color, state: .active,
            createdAt: now, updatedAt: now, revision: 1
        )
        try data.assertUnique(project)
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .project(project), now: now)
        data.projects[project.id] = project
        commit(data, owner: owner)
        return .json(201, data.projectDTO(project))
    }

    mutating func updateProject(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError)
        -> Reply
    {
        let body = try RequestBody(request.body, allowing: ["name", "color", "expected_revision"])
        let rawName = try body.string("name", min: 1, max: GTDLimits.name)
        let color = try body.string("color", max: GTDLimits.color)
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "update_project:\(id)"
        let fingerprint = body.fingerprint(command: command)
        if case .project(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.projectDTO(stored))
        }
        var project = try data.project(id)
        guard project.revision == expected else { throw .stale("Project", id) }
        if body.has("name"), let rawName, !rawName.isEmpty { project.name = NameNormalizer.display(rawName) }
        project.normalizedName = NameNormalizer.project(project.name)
        if body.has("color") { project.color = color }
        project.updatedAt = now
        project.revision += 1
        try data.assertUnique(project)
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .project(project), now: now)
        data.projects[id] = project
        commit(data, owner: owner)
        return .json(200, data.projectDTO(project))
    }

    /// Archiving is not checked against the current state (archiving twice
    /// only bumps the revision) and clears the project from every task.
    mutating func archiveProject(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError)
        -> Reply
    {
        let body = try RequestBody(request.body, allowing: ["expected_revision"])
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "archive_project:\(id)"
        let fingerprint = body.fingerprint(command: command)
        if case .project(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.projectDTO(stored))
        }
        var project = try data.project(id)
        guard project.revision == expected else { throw .stale("Project", id) }
        project.state = .archived
        project.updatedAt = now
        project.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .project(project), now: now)
        data.projects[id] = project
        for task in data.tasks.values where task.projectID == id {
            var updated = task
            updated.projectID = nil
            updated.updatedAt = now
            updated.revision += 1
            data.tasks[task.id] = updated
        }
        commit(data, owner: owner)
        return .json(200, data.projectDTO(project))
    }

    // MARK: - Tags

    func listTags(_ owner: String) -> Reply {
        let data = data(owner)
        let active = data.tags.values.filter { $0.state == .active }
            .sorted { (PythonText.strip($0.name).lowercased(), $0.id) < (PythonText.strip($1.name).lowercased(), $1.id) }
        return .json(200, active.map(data.tagDTO))
    }

    func getTag(_ id: String, owner: String) throws(FakeHTTPError) -> Reply {
        let data = data(owner)
        return .json(200, data.tagDTO(try data.tag(id)))
    }

    mutating func createTag(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["name"])
        let rawName = try body.string("name", required: true, min: 1, max: GTDLimits.name) ?? ""
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "create_tag"
        let fingerprint = body.fingerprint(command: command)
        if case .tag(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(201, data.tagDTO(stored))
        }
        let name = NameNormalizer.tagDisplay(rawName)
        guard !name.isEmpty else { throw .validation(["body", "name"], "String should have at least 1 character") }
        let tag = TagRow(
            id: mint("tag"), name: name, normalizedName: NameNormalizer.tag(name), state: .active, createdAt: now,
            updatedAt: now, revision: 1
        )
        try data.assertUnique(tag)
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .tag(tag), now: now)
        data.tags[tag.id] = tag
        commit(data, owner: owner)
        return .json(201, data.tagDTO(tag))
    }

    mutating func updateTag(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["name", "expected_revision"])
        let rawName = try body.string("name", min: 1, max: GTDLimits.name)
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "update_tag:\(id)"
        let fingerprint = body.fingerprint(command: command)
        if case .tag(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.tagDTO(stored))
        }
        var tag = try data.tag(id)
        guard tag.revision == expected else { throw .stale("Tag", id) }
        if body.has("name"), let rawName, !rawName.isEmpty { tag.name = NameNormalizer.tagDisplay(rawName) }
        tag.normalizedName = NameNormalizer.tag(tag.name)
        tag.updatedAt = now
        tag.revision += 1
        try data.assertUnique(tag)
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .tag(tag), now: now)
        data.tags[id] = tag
        commit(data, owner: owner)
        return .json(200, data.tagDTO(tag))
    }

    /// `DELETE /tags/{id}?expected_revision=N`: a soft delete that removes the
    /// tag from every task. The fingerprint is `{"expected_revision": N}`,
    /// the request model the route builds from the query.
    mutating func deleteTag(_ id: String, _ request: HTTPRequest, query: ListQuery, owner: String, now: Date)
        throws(FakeHTTPError) -> Reply
    {
        guard let raw = query.values("expected_revision").last else {
            throw .validation(["query", "expected_revision"], "Field required", type: "missing")
        }
        guard let expected = Int(raw), expected >= 1 else {
            throw .validation(["query", "expected_revision"], "Input should be a valid integer", type: "int_parsing")
        }
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "delete_tag:\(id)"
        let fingerprint = RequestBody(fields: ["expected_revision": .number(Double(expected))])
            .fingerprint(command: command)
        if case .tag(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.tagDTO(stored))
        }
        var tag = try data.tag(id)
        guard tag.revision == expected else { throw .stale("Tag", id) }
        tag.state = .deleted
        tag.updatedAt = now
        tag.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .tag(tag), now: now)
        data.tags[id] = tag
        for task in data.tasks.values where task.tagIDs.contains(id) {
            var updated = task
            updated.tagIDs.removeAll { $0 == id }
            updated.updatedAt = now
            updated.revision += 1
            data.tasks[task.id] = updated
        }
        commit(data, owner: owner)
        return .json(200, data.tagDTO(tag))
    }
}

extension OwnerData {
    /// `_assert_unique_project_name`: only among active projects.
    func assertUnique(_ project: ProjectRow) throws(FakeHTTPError) {
        guard project.state == .active else { return }
        if projects.values.contains(where: {
            $0.id != project.id && $0.state == .active && $0.normalizedName == project.normalizedName
        }) {
            throw .conflict("Project", project.name)
        }
    }

    /// `_assert_unique_tag_name`: only among active tags.
    func assertUnique(_ tag: TagRow) throws(FakeHTTPError) {
        guard tag.state == .active else { return }
        if tags.values.contains(where: { $0.id != tag.id && $0.state == .active && $0.normalizedName == tag.normalizedName }) {
            throw .conflict("Tag", tag.name)
        }
    }
}
