"use strict";

// Visual layer only. Python owns the MDP, step requests, and timing.
const COLORS = {
  background: 0x050607,
  tile: 0x0c0e10,
  border: 0x292e31,
  panel: 0x0b0d0f,
  divider: 0x252a2d,
  red: 0xe36c70,
  green: 0x6acf9f,
  gold: 0xd4af62,
  cyan: 0x98dce0,
  purple: 0x95a9dc,
  darkButton: 0x14171a,
  disabled: 0x292e31,
  white: "#e9e9e5",
  muted: "#8b9395",
  faint: "#626b6e",
};

const BOARD = { x: 68, y: 240, cell: 142, gap: 10 };
const DEBUG = { x: 758, y: 451, width: 269, height: 355 };
const MONO = "DejaVu Sans Mono, Consolas, monospace";
const SANS = "Arial, Helvetica, sans-serif";
const FONT_SCALE = 1.25;

let socket = null;
let scene = null;
let latest = null;

function send(command) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "control", command }));
  }
}

function connect() {
  socket = new WebSocket("ws://" + location.host + "/ws");

  socket.onopen = () => {
    if (scene) scene.setConnection(true);
  };

  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "state") {
        latest = payload;
        if (scene) scene.applyState(payload);
      }
    } catch (error) {
      console.error("Invalid simulation state", error);
    }
  };

  socket.onclose = () => {
    if (scene) scene.setConnection(false);
  };

  socket.onerror = () => {
    if (scene) scene.setConnection(false);
  };
}

class RobotScene extends Phaser.Scene {
  constructor() {
    super("RobotScene");
    this.cells = [];
    this.buttons = {};
    this.renderTimer = null;
    this.lastRender = 0;
  }

  create() {
    scene = this;
    document.getElementById("loading")?.remove();
    this.cameras.main.setBackgroundColor(COLORS.background);

    this.createHeader();
    this.createBoard();
    this.createConsole();
    this.createControls();

    // The scene is static between incoming states and user interactions.
    // Stop Phaser's continuous loop after each frame; input still uses DOM events.
    this.game.events.on("postrender", () => {
      this.game.loop.sleep();
      this.lastRender = performance.now();
    });
    window.addEventListener("resize", () => {
      this.scale.refresh();
      this.requestRender();
    });
    document.addEventListener("visibilitychange", () => this.requestRender());

    if (latest) this.applyState(latest);
    this.setConnection(socket?.readyState === WebSocket.OPEN);
  }

  requestRender() {
    if (document.hidden || this.renderTimer !== null) return;
    // Coalesce updates and cap drawing at 30 FPS, independent of agent speed.
    const delay = Math.max(0, 1000 / 30 - (performance.now() - this.lastRender));
    this.renderTimer = window.setTimeout(() => {
      this.renderTimer = null;
      if (document.hidden) return;
      this.game.step(performance.now(), 0);
    }, delay);
  }

  text(x, y, value, size, color = COLORS.white, options = {}) {
    const label = this.add.text(x, y, value, {
      fontFamily: options.mono === false ? SANS : MONO,
      fontSize: Math.round(size * FONT_SCALE) + "px",
      color: typeof color === "number"
        ? "#" + color.toString(16).padStart(6, "0")
        : color,
      fontStyle: options.bold ? "bold" : "normal",
      letterSpacing: options.spacing || 0,
      lineSpacing: options.lineSpacing ?? 5,
    });
    label.setOrigin(
      options.originX ?? options.origin ?? 0,
      options.originY ?? options.origin ?? 0
    );
    return label;
  }

  line(x1, y1, x2, y2, color = COLORS.divider, width = 1) {
    const graphics = this.add.graphics();
    graphics.lineStyle(width, color, 1);
    graphics.lineBetween(x1, y1, x2, y2);
  }

  frame(x, y, width, height, radius = 15) {
    const graphics = this.add.graphics();
    graphics.fillStyle(COLORS.panel, 1);
    graphics.fillRoundedRect(x, y, width, height, radius);
    graphics.lineStyle(1, COLORS.border, 1);
    graphics.strokeRoundedRect(x, y, width, height, radius);
    return graphics;
  }

  createHeader() {
    this.text(68, 39, "R L  /  S I M U L A T I O N   L A B", 13, COLORS.gold);
    this.text(68, 75, "FIND THE DOCK", 37, COLORS.white, {
      mono: false, bold: true, spacing: 3,
    });
    this.titleText = this.text(69, 132, "MARKOV DECISION PROCESS     /     GRID WORLD 04 × 04", 15, COLORS.muted);
    this.line(68, 173, 1052, 173);

    this.text(68, 198, "01  /  ENVIRONMENT", 14, COLORS.gold);
    this.text(735, 198, "02  /  TELEMETRY", 14, COLORS.gold);
  }

  createBoard() {
    for (let row = 0; row < 4; row++) {
      this.cells[row] = [];
      for (let col = 0; col < 4; col++) {
        const graphics = this.add.graphics();
        this.cells[row][col] = graphics;
        this.drawCell(graphics, row, col, false, false, false);
      }
    }
  }

  drawCell(graphics, row, col, blocked, charging, occupied) {
    const signature = Number(blocked) | (Number(charging) << 1) | (Number(occupied) << 2);
    if (graphics.cellSignature === signature) return;
    graphics.cellSignature = signature;
    const x = BOARD.x + col * (BOARD.cell + BOARD.gap);
    const y = BOARD.y + row * (BOARD.cell + BOARD.gap);
    const size = BOARD.cell;
    const cx = x + size / 2;
    const cy = y + size / 2;

    const stroke = occupied ? COLORS.border
      : charging ? COLORS.gold
      : blocked ? COLORS.red
      : COLORS.border;

    graphics.clear();
    graphics.fillStyle(COLORS.tile, 1);
    graphics.fillRoundedRect(x, y, size, size, 11);
    graphics.lineStyle(!occupied && (charging || blocked) ? 2 : 1.5, stroke, 1);
    graphics.strokeRoundedRect(x, y, size, size, 11);

    if (blocked) {
      // Angular hazard motif inspired by the reference.
      graphics.lineStyle(3, COLORS.red, 1);
      graphics.beginPath();
      graphics.moveTo(cx - 26, cy + 25);
      graphics.lineTo(cx - 26, cy + 13);
      graphics.lineTo(cx - 13, cy + 13);
      graphics.lineTo(cx - 13, cy);
      graphics.lineTo(cx, cy);
      graphics.lineTo(cx, cy - 13);
      graphics.lineTo(cx + 13, cy - 13);
      graphics.lineTo(cx + 13, cy - 25);
      graphics.lineTo(cx + 26, cy - 25);
      graphics.strokePath();
    }

    if (charging) {
      // Geometric bolt rather than an image asset.
      const bx = occupied ? x + size - 25 : cx;
      const by = occupied ? y + 29 : cy;
      const scale = occupied ? 0.48 : 1;
      const points = [
        [-3, -28], [-19, 3], [-5, 3],
        [-11, 28], [19, -7], [4, -7], [10, -28],
      ];
      graphics.fillStyle(COLORS.gold, 1);
      graphics.beginPath();
      graphics.moveTo(bx + points[0][0] * scale, by + points[0][1] * scale);
      for (const [px, py] of points.slice(1)) {
        graphics.lineTo(bx + px * scale, by + py * scale);
      }
      graphics.closePath();
      graphics.fillPath();
    }

    if (occupied) {
      // Compact robot head, drawn directly in Phaser.
      graphics.lineStyle(3, COLORS.cyan, 0.8);
      graphics.lineBetween(cx, cy - 49, cx, cy - 37);
      graphics.fillStyle(COLORS.cyan, 1);
      graphics.fillCircle(cx, cy - 51, 4);

      graphics.fillStyle(COLORS.cyan, 0.12);
      graphics.fillRoundedRect(cx - 36, cy - 35, 72, 66, 13);
      graphics.lineStyle(3, COLORS.cyan, 1);
      graphics.strokeRoundedRect(cx - 36, cy - 35, 72, 66, 13);

      graphics.fillStyle(COLORS.cyan, 0.75);
      graphics.fillRoundedRect(cx - 44, cy - 12, 7, 24, 3);
      graphics.fillRoundedRect(cx + 37, cy - 12, 7, 24, 3);

      graphics.fillStyle(COLORS.cyan, 1);
      graphics.fillRoundedRect(cx - 24, cy - 11, 14, 12, 4);
      graphics.fillRoundedRect(cx + 10, cy - 11, 14, 12, 4);
      graphics.lineStyle(3, COLORS.cyan, 0.85);
      graphics.lineBetween(cx - 13, cy + 17, cx + 13, cy + 17);
    }
  }

  createConsole() {
    // Tall console sits to the right of the grid.
    this.frame(735, 240, 317, 598, 15);
    this.text(758, 266, "LIVE / TELEMETRY", 13, COLORS.gold);
    this.line(758, 300, 1027, 300);

    this.stepsText = this.text(758, 320, "0 STEPS", 24, COLORS.white);
    this.telemetryStatus = this.text(
      1027, 332, "PAUSED", 11, COLORS.muted, { originX: 1 }
    );

    this.line(758, 383, 1027, 383);
    this.text(758, 408, "DEBUG OUTPUT", 13, COLORS.gold);
    this.line(758, 441, 1027, 441);

    this.debugText = this.text(
      DEBUG.x, DEBUG.y, "Awaiting simulation data…", 14, COLORS.white,
      { lineSpacing: 2 }
    );
    this.debugText.setWordWrapWidth(DEBUG.width, true);

    // Clip overflowing debug lines, but keep them available by scrolling.
    const debugMask = this.make.graphics({ x: 0, y: 0, add: false });
    debugMask.fillStyle(0xffffff);
    debugMask.fillRect(DEBUG.x, DEBUG.y, DEBUG.width, DEBUG.height);
    this.debugText.setMask(debugMask.createGeometryMask());

    this.input.on("wheel", (pointer, _objects, _dx, dy) => {
      if (pointer.x < DEBUG.x || pointer.x > DEBUG.x + DEBUG.width ||
          pointer.y < DEBUG.y || pointer.y > DEBUG.y + DEBUG.height) return;
      const maxScroll = Math.max(0, this.debugText.height - DEBUG.height);
      const currentScroll = DEBUG.y - this.debugText.y;
      const scroll = Phaser.Math.Clamp(currentScroll + dy, 0, maxScroll);
      if (scroll !== currentScroll) {
        this.debugText.y = DEBUG.y - scroll;
        this.requestRender();
      }
    });
  }

  createControls() {
    // Full-width control bar beneath both the grid and debug panel.
    this.frame(68, 861, 984, 166, 15);

    this.text(91, 878, "03 / PLAYBACK", 13, COLORS.gold);
    this.buttons.play = this.button(
      91, 918, 221, 65, "PLAY", COLORS.green, "toggle_play", 20
    );
    this.modeText = this.text(91, 994, "AUTO / PAUSED", 11, COLORS.muted);

    this.line(333, 883, 333, 1009);
    this.text(358, 878, "04 / FRAME RATE", 13, COLORS.gold);
    this.buttons.minus = this.button(
      358, 920, 55, 62, "−", COLORS.darkButton, "fps_down", 22
    );
    this.frame(420, 920, 73, 62, 10);
    this.fpsText = this.text(
      456, 951, "10", 22, COLORS.white, { origin: 0.5 }
    );
    this.buttons.plus = this.button(
      500, 920, 55, 62, "+", COLORS.darkButton, "fps_up", 22
    );
    this.buttons.none = this.button(
      563, 920, 77, 62, "∞", COLORS.darkButton, "fps_toggle", 22
    );
    this.text(358, 995, "STEPS / SECOND  ·  ∞ = 60 SYNCED", 11, COLORS.faint);

    this.line(682, 883, 682, 1009);
    this.text(711, 878, "05 / MANUAL STEP", 13, COLORS.gold);
    this.buttons.step = this.button(
      711, 918, 316, 65, "STEP  →", COLORS.purple, "step", 20
    );
    this.text(711, 994, "ONE ACTION PER CLICK", 11, COLORS.muted);
    this.connectionDot = this.add.circle(925, 1003, 5, COLORS.red);
    this.connectionText = this.text(938, 994, "CONNECTING", 10, COLORS.muted);
  }

  button(x, y, width, height, label, variant, command, fontSize) {
    const graphics = this.add.graphics();
    const caption = this.text(
      x + width / 2, y + height / 2, label, fontSize, COLORS.white,
      { origin: 0.5 }
    );
    const hitbox = this.add.zone(x, y, width, height)
      .setOrigin(0)
      .setInteractive({ useHandCursor: true });

    hitbox.on("pointerdown", () => {
      if (hitbox.input?.enabled) send(command);
    });

    let current = null;
    const button = {
      set(color, value, enabled = true) {
        const signature = [color, value, enabled].join("|");
        if (signature === current) return;
        current = signature;

        const colored = color === COLORS.green || color === COLORS.red
          || color === COLORS.purple || color === COLORS.gold;
        const border = !enabled ? COLORS.disabled
          : colored ? color : COLORS.border;
        const fill = !enabled ? COLORS.panel
          : color === COLORS.red ? 0x251317
          : color === COLORS.green ? 0x12251d
          : color === COLORS.purple ? 0x161d2a
          : color === COLORS.gold ? 0x231d12
          : COLORS.darkButton;

        graphics.clear();
        graphics.fillStyle(fill, 1);
        graphics.fillRoundedRect(x, y, width, height, 10);
        graphics.lineStyle(1.5, border, 1);
        graphics.strokeRoundedRect(x, y, width, height, 10);

        caption.setText(value);
        caption.setColor(
          !enabled ? COLORS.faint
          : colored ? "#" + color.toString(16).padStart(6, "0")
          : COLORS.white
        );

        if (enabled && !hitbox.input?.enabled) {
          hitbox.setInteractive({ useHandCursor: true });
        } else if (!enabled && hitbox.input?.enabled) {
          hitbox.disableInteractive();
        }
      },
    };

    button.set(variant, label);
    return button;
  }

  setConnection(connected) {
    this.connectionDot?.setFillStyle(connected ? COLORS.green : COLORS.red);
    this.connectionText?.setText(connected ? "CONNECTED" : "DISCONNECTED");
    this.requestRender();
  }

  applyState(state) {
    this.requestRender();
    const title = (state.title ?? "Markov Decision Process").toUpperCase();
    this.titleText.setText(title + "     /     GRID WORLD 04 × 04");
    const obstacles = new Set(
      state.obstacles.map(([row, col]) => row + "," + col)
    );
    for (let row = 0; row < 4; row++) {
      for (let col = 0; col < 4; col++) {
        this.drawCell(
          this.cells[row][col], row, col,
          obstacles.has(row + "," + col),
          row === state.dock[0] && col === state.dock[1],
          row === state.robot[0] && col === state.robot[1]
        );
      }
    }

    const finished = state.finished;
    const mode = finished ? "FINISHED"
      : state.playing ? "RUNNING" : "PAUSED";
    this.stepsText.setText(String(state.steps) + " STEPS");
    this.telemetryStatus.setText(mode);
    const debug = state.debug || "No debug output.";
    if (this.debugText.text !== debug) {
      this.debugText.setText(debug);
      this.debugText.y = DEBUG.y;
    }

    // Episode completion is temporary during training; playback stays clickable.
    this.buttons.play.set(
      state.playing ? COLORS.red : COLORS.green,
      state.playing ? "PAUSE" : "PLAY"
    );
    this.modeText.setText("AUTO / " + mode);

    const timed = state.fps !== null;
    this.buttons.minus.set(
      COLORS.darkButton, "−", timed && state.fps > 1
    );
    this.buttons.plus.set(
      COLORS.darkButton, "+", timed && state.fps < 60
    );
    this.buttons.none.set(
      timed ? COLORS.darkButton : COLORS.gold, "∞"
    );
    this.fpsText.setText(timed ? String(state.fps) : "∞");

    this.buttons.step.set(
      !state.playing && !finished ? COLORS.purple : COLORS.disabled,
      "STEP  →", !state.playing && !finished
    );
  }
}

new Phaser.Game({
  // Canvas retains the last frame while idle without a continuous WebGL loop.
  type: Phaser.CANVAS,
  parent: "game",
  width: 1120,
  height: 1060,
  backgroundColor: COLORS.background,
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  render: { pixelArt: false, antialias: true },
  fps: { target: 30, limit: 30, forceSetTimeOut: true },
  audio: { noAudio: true },
  scene: RobotScene,
});

connect();
