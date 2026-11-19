"use strict";

// Phaser owns graphics and input; Python owns state, rewards, and step timing.
const COLORS = {
  background: 0x000000,
  tile: 0x1a1a1a,
  obstacle: 0x660000,
  panel: 0x323642,
  darkButton: 0x1a1a1a,
  disabled: 0x242630,
  green: 0x26ff00,
  red: 0xf53741,
  purple: 0x5159c9,
  white: "#ffffff",
  muted: "#dddde6",
};

let socket = null;
let scene = null;
let latest = null;

function send(command) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "control", command }));
  }
}

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws`);
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
    this.buttons = {};
    this.cells = [];
    this.obstacleGraphics = [];
  }

  preload() {
    this.load.image("robot", "/assets/robot.png");
    this.load.image("dock", "/assets/dock.png");
  }

  create() {
    scene = this;
    document.getElementById("loading").remove();

    this.cameras.main.setBackgroundColor(COLORS.background);
    const background = this.add.graphics();
    background.fillStyle(COLORS.panel, 1);
    background.fillRoundedRect(760, 20, 340, 1020, 20);
    background.fillRoundedRect(20, 800, 720, 240, 20);

    for (let row = 0; row < 4; row++) {
      this.cells[row] = [];
      for (let col = 0; col < 4; col++) {
        const x = 22 + col * 180;
        const y = 22 + row * 180;
        const tile = this.add.graphics();
        tile.fillStyle(COLORS.tile, 1);
        tile.fillRoundedRect(x, y, 176, 176, 20);
        const block = this.add.graphics();
        block.fillStyle(COLORS.obstacle, 1);
        block.fillRoundedRect(x + 18, y + 18, 140, 140, 20);
        block.setVisible(false);
        this.obstacleGraphics.push(block);
        this.cells[row][col] = block;
      }
    }

    this.dock = this.add.image(0, 0, "dock").setDisplaySize(48, 48);
    this.robot = this.add.image(0, 0, "robot").setDisplaySize(112, 112);
    this.stepsText = this.text(40, 758, "Steps: 0", 20);
    this.debugText = this.text(40, 824, "", 20).setWordWrapWidth(680, true);
    this.connectionText = this.text(780, 900, "Connecting…", 18);

    this.buttons.play = this.button(780, 70, 300, 80, "Pause", COLORS.red, "toggle_play", 30);
    this.text(780, 230, "FPS/Speed", 28);
    this.buttons.minus = this.button(780, 304, 60, 60, "−", COLORS.darkButton, "fps_down", 28);
    this.buttons.plus = this.button(920, 304, 60, 60, "+", COLORS.darkButton, "fps_up", 28);
    this.buttons.none = this.button(984, 304, 96, 60, "None", COLORS.darkButton, "fps_toggle", 22);
    this.fpsText = this.text(880, 323, "10", 26).setOrigin(0.5, 0);

    this.text(780, 442, "Step", 28);
    this.buttons.step = this.button(780, 520, 300, 64, "Step", COLORS.purple, "step", 24);

    if (latest) this.applyState(latest);
    this.setConnection(socket?.readyState === WebSocket.OPEN);
  }

  text(x, y, message, size) {
    return this.add.text(x, y, message, {
      fontFamily: "DejaVu Sans Mono, Consolas, monospace",
      fontSize: size + "px",
      color: COLORS.white,
      lineSpacing: 4,
    });
  }

  button(x, y, width, height, label, color, command, fontSize) {
    const graphics = this.add.graphics();
    const text = this.text(x + width / 2, y + height / 2, label, fontSize).setOrigin(0.5);
    const hitbox = this.add.zone(x, y, width, height)
      .setOrigin(0)
      .setInteractive({ useHandCursor: true });
    hitbox.on("pointerdown", () => {
      if (hitbox.input.enabled) send(command);
    });

    const button = {
      graphics, text, hitbox, x, y, width, height,
      set(colorValue, textValue, enabled = true) {
        graphics.clear().fillStyle(colorValue, 1);
        graphics.fillRoundedRect(x, y, width, height, 20);
        text.setText(textValue);
        text.setColor(enabled ? COLORS.white : COLORS.muted);
        if (enabled && !hitbox.input?.enabled) {
          hitbox.setInteractive({ useHandCursor: true });
        } else if (!enabled && hitbox.input?.enabled) {
          hitbox.disableInteractive();
        }
      },
    };
    button.set(color, label);
    return button;
  }

  setConnection(connected) {
    this.connectionText?.setText(connected ? "Connected" : "Disconnected");
  }

  applyState(state) {
    const obstacles = new Set(state.obstacles.map(([row, col]) => `${row},${col}`));
    for (let row = 0; row < 4; row++) {
      for (let col = 0; col < 4; col++) {
        this.cells[row][col].setVisible(obstacles.has(`${row},${col}`));
      }
    }

    const [dockRow, dockCol] = state.dock;
    this.dock.setPosition(22 + dockCol * 180 + 149, 22 + dockRow * 180 + 149);

    const [row, col] = state.robot;
    const atDock = row === dockRow && col === dockCol;
    this.robot.setPosition(
      22 + col * 180 + 88 - (atDock ? 30 : 0),
      22 + row * 180 + 88 - (atDock ? 30 : 0)
    );

    const status = state.success ? "Charging complete!"
      : state.truncated ? "Step limit reached"
      : `Steps: ${state.steps}`;
    this.stepsText.setText(status);
    this.debugText.setText(state.debug || "");

    const finished = state.success || state.truncated;
    this.buttons.play.set(
      finished ? COLORS.disabled : state.playing ? COLORS.red : COLORS.green,
      state.playing ? "Pause" : "Play",
      !finished
    );
    const hasFps = state.fps !== null;
    this.buttons.minus.set(
      !hasFps || state.fps <= 1 ? COLORS.disabled : COLORS.darkButton, "−",
      hasFps && state.fps > 1
    );
    this.buttons.plus.set(
      !hasFps || state.fps >= 60 ? COLORS.disabled : COLORS.darkButton, "+",
      hasFps && state.fps < 60
    );
    this.buttons.none.set(
      hasFps ? COLORS.darkButton : COLORS.purple, "None"
    );
    this.fpsText.setText(hasFps ? String(state.fps) : "∞");
    this.buttons.step.set(
      !state.playing && !finished ? COLORS.purple : COLORS.disabled, "Step",
      !state.playing && !finished
    );
  }
}

new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: 1120,
  height: 1060,
  backgroundColor: COLORS.background,
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  render: { pixelArt: false, antialias: true },
  scene: RobotScene,
});

connect();
