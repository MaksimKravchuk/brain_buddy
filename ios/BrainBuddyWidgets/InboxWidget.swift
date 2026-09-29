import AppIntents
import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import WidgetKit

/// The Inbox widget has nothing to configure. It uses an App Intent
/// configuration anyway because that gives it WidgetKit's async timeline
/// provider; the static provider hands out completion handlers, which do not
/// cross into the main-actor store cleanly under Swift 6 checking.
struct InboxConfigurationIntent: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Inbox"

    static let description = IntentDescription("Shows how many items wait in your inbox.")

    init() {}
}

struct InboxEntry: TimelineEntry, Sendable {
    let date: Date
    /// Projectless Inbox tasks, the same number as the app's Inbox badge.
    let count: Int
    /// False when the store could not be read (for example before the first unlock).
    let isAvailable: Bool

    static func sample(at date: Date = Date()) -> InboxEntry {
        InboxEntry(date: date, count: 3, isAvailable: true)
    }
}

@MainActor
enum InboxLoader {
    static func load(at date: Date = Date()) async -> InboxEntry {
        let workspace = await SharedWorkspace.make()
        guard workspace.isLoaded, workspace.loadError == nil else {
            return InboxEntry(date: date, count: 0, isAvailable: false)
        }
        return InboxEntry(date: date, count: workspace.counts().inbox, isAvailable: true)
    }
}

struct InboxProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> InboxEntry {
        .sample()
    }

    func snapshot(for configuration: InboxConfigurationIntent, in context: Context) async -> InboxEntry {
        if context.isPreview {
            return .sample()
        }
        return await InboxLoader.load()
    }

    func timeline(for configuration: InboxConfigurationIntent, in context: Context) async -> Timeline<InboxEntry> {
        let entry = await InboxLoader.load()
        return Timeline(entries: [entry], policy: .after(WidgetSchedule.nextMidnight(after: entry.date)))
    }
}

/// Inbox count on the Home Screen and the Lock Screen. Every size opens the
/// app on the capture sheet.
struct InboxWidget: Widget {
    static let kind = "com.brainbuddy.ios.widget.inbox"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(
            kind: Self.kind,
            intent: InboxConfigurationIntent.self,
            provider: InboxProvider()
        ) { entry in
            InboxWidgetView(entry: entry)
        }
        .configurationDisplayName("Inbox")
        .description("What's waiting in your inbox. Tap to capture something new.")
        .supportedFamilies([.systemSmall, .accessoryCircular, .accessoryRectangular, .accessoryInline])
    }
}

struct InboxWidgetView: View {
    let entry: InboxEntry

    @Environment(\.widgetFamily) private var family
    @Environment(\.colorScheme) private var colorScheme

    private var palette: WidgetPalette { WidgetPalette(colorScheme: colorScheme) }

    var body: some View {
        content
            .widgetURL(SharedConstants.captureURL)
            .containerBackground(palette.background, for: .widget)
    }

    @ViewBuilder private var content: some View {
        switch family {
        case .accessoryCircular: circular
        case .accessoryRectangular: rectangular
        case .accessoryInline: inline
        default: small
        }
    }

    // MARK: Copy

    /// "3 to process" or "Inbox is clear".
    private var status: String {
        entry.count == 0 ? "Inbox is clear" : "\(entry.count) to process"
    }

    /// "3 in Inbox" or "Inbox is clear", for the one-line Lock Screen slot.
    private var inlineStatus: String {
        guard entry.isAvailable else { return "Brain Buddy" }
        return entry.count == 0 ? "Inbox is clear" : "\(entry.count) in Inbox"
    }

    private var countText: String {
        entry.isAvailable ? "\(entry.count)" : "–"
    }

    private var accessibilityStatus: String {
        guard entry.isAvailable else { return "Inbox unavailable. Open Brain Buddy." }
        switch entry.count {
        case 0: return "Inbox is clear"
        case 1: return "1 item in Inbox"
        default: return "\(entry.count) items in Inbox"
        }
    }

    // MARK: Families

    private var small: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label {
                Text("Inbox")
                    .foregroundStyle(palette.primaryText)
            } icon: {
                Image(systemName: "tray")
                    .foregroundStyle(palette.accent)
                    .widgetAccentable()
            }
            .font(.caption.weight(.semibold))

            if entry.isAvailable {
                Text(entry.count, format: .number)
                    .font(.system(size: 40, weight: .semibold))
                    .monospacedDigit()
                    .foregroundStyle(palette.primaryText)
                    .contentTransition(.numericText())
                    .accessibilityLabel(accessibilityStatus)
                // The count's accessibility label already says this.
                Group {
                    if entry.count == 0 {
                        Text("Inbox is clear")
                    } else {
                        Text("to process")
                    }
                }
                .font(.footnote)
                .foregroundStyle(palette.secondaryText)
                .accessibilityHidden(true)
            } else {
                Text("Open Brain Buddy to see your inbox.")
                    .font(.footnote)
                    .foregroundStyle(palette.secondaryText)
            }

            Spacer(minLength: 0)

            Label("Capture", systemImage: "plus.circle.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(palette.accentText)
                .widgetAccentable()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var circular: some View {
        ZStack {
            AccessoryWidgetBackground()
            VStack(spacing: 0) {
                Image(systemName: "tray")
                    .font(.caption)
                    .widgetAccentable()
                Text(countText)
                    .font(.title3.weight(.semibold))
                    .monospacedDigit()
                    .minimumScaleFactor(0.5)
                    .lineLimit(1)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityStatus)
    }

    private var rectangular: some View {
        VStack(alignment: .leading, spacing: 1) {
            Label("Inbox", systemImage: "tray")
                .font(.headline)
                .widgetAccentable()
            Text(entry.isAvailable ? status : "Open Brain Buddy")
                .font(.body)
            Text("Tap to capture")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private var inline: some View {
        Label {
            Text(inlineStatus)
        } icon: {
            Image(systemName: "tray")
        }
    }
}
