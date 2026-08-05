import Foundation

public actor BrainBuddyAPIClient {
    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder

    public init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.decoder.dateDecodingStrategy = .iso8601
    }

    public func signUp(email: String, password: String, inviteCode: String) async throws -> SessionUser {
        try await send("api/auth/signup", method: "POST", body: [
            "email": email, "password": password, "invite_code": inviteCode,
        ])
    }

    public func signIn(email: String, password: String) async throws -> SessionUser {
        try await send("api/auth/login", method: "POST", body: ["email": email, "password": password])
    }

    public func currentUser() async throws -> SessionUser {
        try await send("api/auth/me", method: "GET", body: Optional<[String: String]>.none)
    }

    public func signOut() async throws {
        let _: EmptyResponse = try await send("api/auth/logout", method: "POST", body: Optional<[String: String]>.none)
    }

    private func send<Response: Decodable, Body: Encodable>(
        _ path: String, method: String, body: Body?
    ) async throws -> Response {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.http(status: http.statusCode, message: Self.errorMessage(from: data))
        }
        if Response.self == EmptyResponse.self, data.isEmpty {
            return EmptyResponse() as! Response
        }
        return try decoder.decode(Response.self, from: data)
    }

    private static func errorMessage(from data: Data) -> String {
        (try? JSONDecoder().decode(ErrorEnvelope.self, from: data).detail) ?? "The server could not complete the request."
    }

    public enum APIError: Error, Equatable {
        case invalidResponse
        case http(status: Int, message: String)
    }
}

private struct ErrorEnvelope: Decodable { let detail: String }
private struct EmptyResponse: Codable {}
