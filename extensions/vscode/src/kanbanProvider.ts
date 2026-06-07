/**
 * Kanban TreeDataProvider for the Agent Bridge VSC sidebar.
 *
 * Displays plans and their tasks grouped by status in a tree view.
 */

import * as vscode from "vscode";
import { type PlanInfo, type TaskInfo } from "./types";

// ── Tree item ──────────────────────────────────────────────────────

export class KanbanTreeItem extends vscode.TreeItem {
  /**
   * Pre-computed child task items for header nodes.
   * Set by the provider when building the tree so lazy-loaded
   * `getChildren` calls for a header can return them immediately.
   */
  public taskItems?: KanbanTreeItem[];

  constructor(
    public readonly label: string,
    public readonly type: "plan" | "task" | "header" | "empty",
    public readonly item?: PlanInfo | TaskInfo,
  ) {
    super(label);

    switch (type) {
      case "plan":
        this.collapsibleState = vscode.TreeItemCollapsibleState.Collapsed;
        break;
      case "header":
        // Headers are collapsible so getChildren can return tasks under them
        this.collapsibleState = vscode.TreeItemCollapsibleState.Collapsed;
        break;
      default:
        this.collapsibleState = vscode.TreeItemCollapsibleState.None;
    }

    this.contextValue = type;

    if (type === "plan" && item) {
      this.tooltip = (item as PlanInfo).description;
    } else if (type === "task" && item) {
      this.tooltip = (item as TaskInfo).description;
    }
  }
}

// ── Provider ───────────────────────────────────────────────────────

const STATUS_GROUPS = [
  { status: "pending", label: "Pending", emoji: "📋" },
  { status: "in_progress", label: "In Progress", emoji: "🔧" },
  { status: "review", label: "Review", emoji: "👁" },
  { status: "approved", label: "Approved", emoji: "✅" },
] as const;

const TASK_EMOJI: Record<string, string> = {
  pending: "⏳",
  in_progress: "🔧",
  review: "👁",
  approved: "✅",
};

export class KanbanTreeProvider
  implements vscode.TreeDataProvider<KanbanTreeItem>
{
  private _plans: PlanInfo[] = [];
  private _tasks: TaskInfo[] = [];

  private _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor() {
    this._plans = [];
    this._tasks = [];
  }

  /**
   * Replace the stored plans and tasks, filtering tasks to only those
   * associated with known plans, then fire the tree change event.
   */
  refresh(plans: PlanInfo[], tasks: TaskInfo[]): void {
    this._plans = plans;
    const planIds = new Set(plans.map((p) => p.id));
    this._tasks = tasks.filter((t) => planIds.has(t.planId));
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: KanbanTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: KanbanTreeItem): KanbanTreeItem[] {
    // ── Root level: plans or empty state ────────────────────────
    if (!element) {
      if (this._plans.length === 0) {
        return [new KanbanTreeItem("No plans", "empty")];
      }

      return this._plans.map((plan) => {
        const taskCount = this._tasks.filter(
          (t) => t.planId === plan.id,
        ).length;
        const item = new KanbanTreeItem(`📋 ${plan.title}`, "plan", plan);
        item.description = `${plan.status} - ${taskCount} tasks`;
        return item;
      });
    }

    // ── Plan level: status-group headers ────────────────────────
    if (element.type === "plan") {
      const plan = element.item as PlanInfo;
      const planTasks = this._tasks.filter((t) => t.planId === plan.id);

      const headers: KanbanTreeItem[] = [];

      for (const group of STATUS_GROUPS) {
        const tasksInGroup = planTasks.filter(
          (t) => t.status === group.status,
        );
        if (tasksInGroup.length === 0) continue;

        const header = new KanbanTreeItem(
          `${group.emoji} ${group.label}`,
          "header",
        );

        header.taskItems = tasksInGroup.map((task) => {
          const emoji = TASK_EMOJI[task.status] ?? "⏳";
          const desc = task.assignee
            ? `${task.status} - ${task.assignee}`
            : task.status;
          const taskItem = new KanbanTreeItem(
            `${emoji} ${task.title}`,
            "task",
            task,
          );
          taskItem.description = desc;
          return taskItem;
        });

        headers.push(header);
      }

      return headers;
    }

    // ── Header level: return pre-computed task items ────────────
    if (element.type === "header") {
      return element.taskItems ?? [];
    }

    return [];
  }
}
