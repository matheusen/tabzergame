extends CharacterBody2D

enum State {
	IDLE,
	PATROL,
	CHASE,
	KEEP_DISTANCE,
	AIM,
	FIRE,
	RECOVER,
	MELEE,
	HURT,
	DOWN,
}

enum MeleeKind {
	PUNCH,
	KICK,
}

enum AgentKind {
	AGENT3,
	EXECUTOR,
	GLITCH,
}

const AGENT_FRAMES := {
	"idle": [
		Rect2(47, 56, 60, 152),
		Rect2(153, 56, 58, 152),
	],
	"walk": [
		Rect2(297, 56, 80, 152),
		Rect2(421, 56, 78, 152),
		Rect2(548, 56, 79, 152),
		Rect2(674, 56, 79, 152),
	],
	"run": [
		Rect2(828, 56, 89, 152),
		Rect2(959, 56, 89, 152),
		Rect2(1084, 56, 99, 152),
		Rect2(1216, 56, 101, 152),
	],
	"aim": [
		Rect2(1396, 56, 105, 152),
		Rect2(1515, 56, 97, 152),
	],
	"fire": [
		Rect2(1669, 56, 106, 152),
		Rect2(1807, 56, 117, 152),
		Rect2(1939, 56, 96, 152),
	],
	"point": [
		Rect2(40, 296, 104, 152),
		Rect2(211, 296, 92, 152),
	],
	"punch": [
		Rect2(432, 296, 90, 152),
		Rect2(558, 296, 118, 152),
		Rect2(694, 296, 119, 152),
		Rect2(826, 296, 82, 152),
	],
	"kick": [
		Rect2(983, 296, 77, 152),
		Rect2(1124, 296, 101, 152),
		Rect2(1252, 296, 120, 152),
		Rect2(1386, 296, 78, 152),
	],
	"crouch": [
		Rect2(1529, 296, 80, 152),
		Rect2(1654, 296, 68, 152),
	],
	"crouch_aim": [
		Rect2(1818, 296, 111, 152),
		Rect2(1997, 296, 111, 152),
	],
	"crouch_shoot": [
		Rect2(56, 520, 112, 152),
		Rect2(235, 520, 108, 152),
	],
	"hurt": [
		Rect2(516, 520, 90, 152),
		Rect2(672, 520, 86, 152),
	],
	"knockdown": [
		Rect2(883, 520, 118, 152),
		Rect2(1074, 520, 163, 152),
	],
	"getup": [
		Rect2(1389, 520, 101, 152),
		Rect2(1545, 520, 82, 152),
	],
}

const EXECUTOR_FRAMES := {
	"idle": [
		Rect2(54, 142, 76, 154),
		Rect2(164, 142, 78, 154),
	],
	"walk": [
		Rect2(306, 145, 88, 151),
		Rect2(424, 145, 86, 151),
		Rect2(543, 145, 88, 151),
		Rect2(661, 145, 88, 151),
	],
	"run": [
		Rect2(786, 146, 98, 150),
		Rect2(904, 146, 98, 150),
		Rect2(1022, 146, 98, 150),
		Rect2(1140, 146, 98, 150),
	],
	"aim": [
		Rect2(1300, 143, 108, 153),
		Rect2(1477, 132, 104, 164),
	],
	"fire": [
		Rect2(1300, 143, 108, 153),
		Rect2(1477, 132, 104, 164),
	],
	"point": [
		Rect2(1300, 143, 108, 153),
		Rect2(1477, 132, 104, 164),
	],
	"punch": [
		Rect2(44, 386, 130, 140),
		Rect2(190, 386, 116, 140),
		Rect2(337, 386, 126, 140),
	],
	"kick": [
		Rect2(525, 386, 102, 140),
		Rect2(654, 386, 102, 140),
		Rect2(778, 374, 116, 152),
		Rect2(909, 386, 118, 140),
	],
	"crouch": [
		Rect2(611, 620, 96, 125),
		Rect2(758, 620, 96, 125),
	],
	"crouch_aim": [
		Rect2(934, 620, 110, 125),
		Rect2(1090, 620, 116, 125),
	],
	"crouch_shoot": [
		Rect2(934, 620, 110, 125),
		Rect2(1090, 620, 116, 125),
	],
	"hurt": [
		Rect2(1354, 604, 104, 142),
		Rect2(1510, 604, 104, 142),
	],
	"knockdown": [
		Rect2(420, 828, 170, 90),
		Rect2(616, 850, 170, 68),
	],
	"getup": [
		Rect2(910, 827, 96, 92),
		Rect2(1087, 826, 100, 92),
	],
}

const GLITCH_FRAMES := {
	"idle": [
		Rect2(58, 58, 90, 160),
		Rect2(176, 58, 88, 160),
	],
	"walk": [
		Rect2(334, 58, 98, 160),
		Rect2(447, 58, 96, 160),
		Rect2(555, 58, 98, 160),
		Rect2(662, 58, 104, 160),
	],
	"run": [
		Rect2(852, 78, 140, 140),
		Rect2(1008, 78, 130, 140),
		Rect2(1160, 78, 150, 140),
		Rect2(1306, 78, 190, 140),
	],
	"aim": [
		Rect2(52, 285, 92, 146),
		Rect2(216, 285, 130, 146),
	],
	"fire": [
		Rect2(492, 285, 172, 146),
		Rect2(672, 285, 196, 146),
		Rect2(868, 285, 206, 146),
	],
	"point": [
		Rect2(1168, 285, 126, 146),
		Rect2(1360, 285, 96, 146),
	],
	"punch": [
		Rect2(36, 486, 120, 124),
		Rect2(204, 486, 136, 124),
		Rect2(376, 486, 164, 124),
		Rect2(578, 486, 126, 124),
	],
	"kick": [
		Rect2(884, 482, 112, 128),
		Rect2(1028, 458, 150, 152),
		Rect2(1208, 458, 220, 152),
		Rect2(1388, 486, 110, 124),
	],
	"crouch": [
		Rect2(36, 668, 102, 94),
		Rect2(176, 676, 116, 86),
	],
	"crouch_aim": [
		Rect2(416, 668, 136, 94),
		Rect2(580, 668, 126, 94),
	],
	"crouch_shoot": [
		Rect2(816, 676, 132, 90),
		Rect2(976, 676, 206, 90),
	],
	"hurt": [
		Rect2(1248, 658, 116, 108),
		Rect2(1418, 656, 112, 110),
	],
	"knockdown": [
		Rect2(52, 816, 146, 90),
		Rect2(240, 858, 170, 48),
	],
	"getup": [
		Rect2(578, 804, 138, 102),
		Rect2(816, 802, 120, 104),
	],
}

@export var target_path: NodePath
@export var agent_kind: AgentKind = AgentKind.AGENT3
@export var sprite_sheet: Texture2D
@export var can_shoot: bool = true
@export var max_health: int = 90
@export var move_speed: float = 138.0
@export var run_speed: float = 232.0
@export var backstep_speed: float = 110.0
@export var gravity_multiplier: float = 1.65

@export var detect_range: float = 900.0
@export var lose_interest_range: float = 1100.0
@export var vertical_engage_range: float = 200.0

@export var melee_lock_range: float = 170.0
@export var melee_y_tolerance: float = 115.0
@export var shoot_min_range: float = 380.0
@export var shoot_ideal_range: float = 640.0
@export var shoot_max_range: float = 820.0
@export var range_tolerance: float = 60.0
@export var patrol_distance: float = 260.0

@export var aim_time: float = 0.32
@export var fire_time: float = 0.28
@export var recover_time: float = 0.46
@export var punch_windup_time: float = 0.12
@export var punch_active_time: float = 0.18
@export var punch_recover_time: float = 0.30
@export var kick_windup_time: float = 0.16
@export var kick_active_time: float = 0.20
@export var kick_recover_time: float = 0.34
@export var melee_lunge_speed: float = 240.0
@export var shoot_cooldown: float = 1.1
@export var melee_cooldown: float = 1.25

@export var melee_damage: int = 10
@export var kick_damage: int = 14
@export var melee_knockback: float = 420.0
@export var kick_knockback: float = 520.0
@export var melee_lift: float = -110.0
@export var melee_reach: float = 170.0
@export var bullet_damage: int = 13
@export var muzzle_offset := Vector2(56.0, -121.0)
@export var bullet_color := Color(1.0, 0.08, 0.06, 1.0)

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var hurtbox: Area2D = $Hurtbox
@onready var melee_hitbox: Area2D = $MeleeHitbox

var target: Node2D
var base_sprite_position := Vector2.ZERO
var health: int
var state: State = State.IDLE
var facing := 1.0
var patrol_origin := Vector2.ZERO
var patrol_direction := -1.0
var state_time := 0.0
var shoot_timer := 0.0
var melee_timer := 0.0
var has_fired_this_cycle := false
var has_melee_hit_this_cycle := false
var melee_is_active := false
var current_melee_kind: MeleeKind = MeleeKind.PUNCH
var next_melee_kind: MeleeKind = MeleeKind.PUNCH


func _ready() -> void:
	add_to_group("enemy")
	health = max_health
	target = get_node_or_null(target_path) as Node2D
	patrol_origin = global_position
	base_sprite_position = sprite.position
	sprite.sprite_frames = _create_sprite_frames()
	sprite.play("idle")
	sprite.animation_finished.connect(_on_animation_finished)
	melee_hitbox.monitoring = false
	melee_hitbox.body_entered.connect(_on_melee_body_entered)
	_enter_state(State.PATROL)


func _physics_process(delta: float) -> void:
	if state == State.DOWN:
		return

	state_time = max(state_time - delta, 0.0)
	shoot_timer = max(shoot_timer - delta, 0.0)
	melee_timer = max(melee_timer - delta, 0.0)

	_apply_gravity(delta)

	if _should_force_melee():
		_enter_state(State.MELEE)

	match state:
		State.IDLE:
			_tick_idle(delta)
		State.PATROL:
			_tick_patrol(delta)
		State.CHASE:
			_tick_chase(delta)
		State.KEEP_DISTANCE:
			_tick_keep_distance(delta)
		State.AIM:
			_tick_aim(delta)
		State.FIRE:
			_tick_fire(delta)
		State.RECOVER:
			_tick_recover(delta)
		State.MELEE:
			_tick_melee(delta)
		State.HURT:
			_tick_hurt(delta)

	move_and_slide()


func take_damage(amount: int) -> void:
	if state == State.DOWN:
		return

	health = max(health - amount, 0)
	if health <= 0:
		_enter_state(State.DOWN)
		return

	_enter_state(State.HURT)


func _tick_idle(delta: float) -> void:
	_slow_down(delta)
	_play_if_needed(&"idle")
	if not _has_target():
		if state_time <= 0.0:
			_enter_state(State.PATROL)
		return

	if _can_see_target():
		_enter_state(State.CHASE)
	elif state_time <= 0.0:
		_enter_state(State.PATROL)


func _tick_patrol(delta: float) -> void:
	if _can_see_target():
		_enter_state(State.CHASE)
		return

	if abs(global_position.x - patrol_origin.x) >= patrol_distance:
		patrol_direction *= -1.0

	_set_facing(patrol_direction)
	velocity.x = patrol_direction * move_speed * 0.55
	_play_if_needed(&"walk")

	if state_time <= 0.0:
		_enter_state(State.IDLE)


func _tick_chase(delta: float) -> void:
	if not _has_target() or _target_distance_x() > lose_interest_range:
		_enter_state(State.PATROL)
		return

	_face_target()
	var distance := _target_distance_x()

	if _is_in_melee_zone():
		if melee_timer <= 0.0:
			_enter_state(State.MELEE)
		else:
			_enter_state(State.KEEP_DISTANCE)
		return

	if not can_shoot:
		velocity.x = facing * run_speed
		_play_if_needed(&"run")
		return

	if distance < shoot_min_range:
		_enter_state(State.KEEP_DISTANCE)
	elif distance >= shoot_min_range and distance <= shoot_max_range:
		if shoot_timer <= 0.0:
			_enter_state(State.AIM)
		else:
			velocity.x = facing * move_speed * 0.55
			_play_if_needed(&"walk")
	else:
		velocity.x = facing * run_speed
		_play_if_needed(&"run")


func _tick_keep_distance(delta: float) -> void:
	if not _has_target():
		_enter_state(State.PATROL)
		return

	if not can_shoot:
		_enter_state(State.CHASE)
		return

	_face_target()
	var distance := _target_distance_x()

	if _is_in_melee_zone() and melee_timer <= 0.0:
		_enter_state(State.MELEE)
		return

	if distance >= shoot_min_range + 40.0:
		if shoot_timer <= 0.0 and distance <= shoot_max_range:
			_enter_state(State.AIM)
		else:
			_enter_state(State.CHASE)
		return

	velocity.x = -facing * backstep_speed
	_play_if_needed(&"walk")


func _tick_aim(delta: float) -> void:
	if not _has_target():
		_enter_state(State.PATROL)
		return
	if not can_shoot:
		_enter_state(State.CHASE)
		return

	if _is_in_melee_zone():
		_enter_state(State.MELEE if melee_timer <= 0.0 else State.KEEP_DISTANCE)
		return

	var distance := _target_distance_x()
	if distance < shoot_min_range:
		_enter_state(State.KEEP_DISTANCE)
		return

	_face_target()
	_slow_down(delta)
	_play_if_needed(&"aim")

	if state_time <= 0.0:
		_enter_state(State.FIRE)


func _tick_fire(delta: float) -> void:
	if not can_shoot:
		_enter_state(State.CHASE)
		return

	if _is_in_melee_zone():
		_enter_state(State.MELEE if melee_timer <= 0.0 else State.KEEP_DISTANCE)
		return

	var distance := _target_distance_x()
	if distance < shoot_min_range:
		_enter_state(State.KEEP_DISTANCE)
		return

	_face_target()
	_slow_down(delta)
	_play_if_needed(&"fire")

	if not has_fired_this_cycle and sprite.frame >= 1:
		has_fired_this_cycle = true
		_shoot()

	if state_time <= 0.0:
		_enter_state(State.RECOVER)


func _tick_recover(delta: float) -> void:
	if not can_shoot:
		_enter_state(State.CHASE if _can_see_target() else State.PATROL)
		return

	if _is_in_melee_zone():
		_enter_state(State.MELEE if melee_timer <= 0.0 else State.KEEP_DISTANCE)
		return

	_slow_down(delta)
	_play_if_needed(&"point")

	if state_time <= 0.0:
		_enter_state(State.CHASE if _can_see_target() else State.PATROL)


func _tick_melee(delta: float) -> void:
	_face_target()
	var anim_name: StringName = &"kick" if current_melee_kind == MeleeKind.KICK else &"punch"
	_play_if_needed(anim_name)

	var active_time := kick_active_time if current_melee_kind == MeleeKind.KICK else punch_active_time
	var recover_time_for_kind := kick_recover_time if current_melee_kind == MeleeKind.KICK else punch_recover_time
	var active_start_time := active_time + recover_time_for_kind
	var active_end_time := recover_time_for_kind
	var lunge_factor := 1.15 if current_melee_kind == MeleeKind.KICK else 1.0
	if state_time <= active_start_time and state_time > active_end_time:
		if not melee_is_active:
			melee_is_active = true
			melee_hitbox.monitoring = true
		velocity.x = facing * melee_lunge_speed * lunge_factor
		_try_apply_melee_damage()
	else:
		if melee_is_active:
			melee_is_active = false
			melee_hitbox.monitoring = false
		_slow_down(delta)

	if state_time <= 0.0:
		melee_hitbox.monitoring = false
		melee_is_active = false
		_enter_state(State.CHASE if _can_see_target() else State.PATROL)


func _tick_hurt(delta: float) -> void:
	velocity.x = move_toward(velocity.x, 0.0, move_speed * delta * 5.0)
	_play_if_needed(&"hurt")
	if state_time <= 0.0:
		_enter_state(State.CHASE if _can_see_target() else State.PATROL)


func _enter_state(next_state: State) -> void:
	state = next_state
	has_fired_this_cycle = false
	melee_hitbox.monitoring = false
	melee_is_active = false
	sprite.position = base_sprite_position

	match state:
		State.IDLE:
			state_time = randf_range(0.55, 1.05)
			velocity.x = 0.0
			_play_if_needed(&"idle")
		State.PATROL:
			state_time = randf_range(1.2, 2.4)
			_play_if_needed(&"walk")
		State.CHASE:
			_play_if_needed(&"run")
		State.KEEP_DISTANCE:
			_play_if_needed(&"walk")
		State.AIM:
			state_time = aim_time
			velocity.x = 0.0
			_play_if_needed(&"aim")
		State.FIRE:
			state_time = fire_time
			velocity.x = 0.0
			_play_if_needed(&"fire")
		State.RECOVER:
			state_time = recover_time
			velocity.x = 0.0
			_play_if_needed(&"point")
		State.MELEE:
			current_melee_kind = next_melee_kind
			next_melee_kind = MeleeKind.KICK if current_melee_kind == MeleeKind.PUNCH else MeleeKind.PUNCH
			var windup := kick_windup_time if current_melee_kind == MeleeKind.KICK else punch_windup_time
			var active := kick_active_time if current_melee_kind == MeleeKind.KICK else punch_active_time
			var recover := kick_recover_time if current_melee_kind == MeleeKind.KICK else punch_recover_time
			state_time = windup + active + recover
			melee_timer = melee_cooldown
			shoot_timer = max(shoot_timer, 0.4)
			has_melee_hit_this_cycle = false
			_update_melee_hitbox_direction()
			velocity.x = 0.0
			_play_if_needed(&"kick" if current_melee_kind == MeleeKind.KICK else &"punch")
		State.HURT:
			state_time = 0.28
			velocity.x = -facing * 128.0
			_play_if_needed(&"hurt")
		State.DOWN:
			_die()


func _shoot() -> void:
	if not can_shoot:
		return
	if _is_in_melee_zone():
		return

	shoot_timer = shoot_cooldown
	var bullet := _create_bullet()
	get_tree().current_scene.add_child(bullet)

	var shot_direction := Vector2(facing, 0.0)
	var muzzle := global_position + Vector2(muzzle_offset.x * facing, muzzle_offset.y)
	bullet.set("damage", bullet_damage)
	bullet.call("setup", muzzle, shot_direction)


func _create_bullet() -> Area2D:
	var bullet := Area2D.new()
	bullet.name = "EnemyBullet"
	bullet.collision_layer = 0
	bullet.collision_mask = 1
	bullet.script = load("res://scripts/enemy_bullet.gd")

	var tracer := Line2D.new()
	tracer.name = "Tracer"
	tracer.points = PackedVector2Array([Vector2(-22, 0), Vector2(22, 0)])
	tracer.width = 4.0
	tracer.default_color = bullet_color
	bullet.add_child(tracer)

	var glow := Line2D.new()
	glow.name = "Glow"
	glow.points = PackedVector2Array([Vector2(-12, 0), Vector2(12, 0)])
	glow.width = 8.0
	glow.default_color = Color(bullet_color.r, bullet_color.g, bullet_color.b, 0.35)
	bullet.add_child(glow)

	var shape := CollisionShape2D.new()
	var rect := RectangleShape2D.new()
	rect.size = Vector2(34.0, 8.0)
	shape.shape = rect
	bullet.add_child(shape)
	return bullet


func _die() -> void:
	velocity = Vector2.ZERO
	collision_shape.disabled = true
	hurtbox.monitoring = false
	melee_hitbox.monitoring = false
	_play_if_needed(&"knockdown")
	await get_tree().create_timer(1.6).timeout
	queue_free()


func _apply_gravity(delta: float) -> void:
	if is_on_floor():
		return

	var gravity := float(ProjectSettings.get_setting("physics/2d/default_gravity"))
	velocity.y += gravity * gravity_multiplier * delta


func _slow_down(delta: float) -> void:
	velocity.x = move_toward(velocity.x, 0.0, move_speed * delta * 5.0)


func _has_target() -> bool:
	return target != null and is_instance_valid(target)


func _can_see_target() -> bool:
	if not _has_target():
		return false

	var to_target := target.global_position - global_position
	return abs(to_target.x) <= detect_range and abs(to_target.y) <= vertical_engage_range


func _target_distance_x() -> float:
	if not _has_target():
		return INF

	return abs(target.global_position.x - global_position.x)


func _face_target() -> void:
	if not _has_target():
		return

	var delta_x := target.global_position.x - global_position.x
	if abs(delta_x) > 4.0:
		_set_facing(sign(delta_x))


func _set_facing(direction: float) -> void:
	if direction == 0.0:
		return

	facing = sign(direction)
	sprite.flip_h = facing < 0.0
	_update_melee_hitbox_direction()


func _update_melee_hitbox_direction() -> void:
	melee_hitbox.position.x = 92.0 * facing


func _on_melee_body_entered(body: Node2D) -> void:
	if has_melee_hit_this_cycle:
		return

	if body.is_in_group("player"):
		_apply_melee_hit_to_target(body)


func _try_apply_melee_damage() -> void:
	if has_melee_hit_this_cycle or not _has_target():
		return

	if _is_target_in_zone(melee_reach, melee_y_tolerance):
		_apply_melee_hit_to_target(target)


func _apply_melee_hit_to_target(player: Node) -> void:
	if has_melee_hit_this_cycle:
		return

	has_melee_hit_this_cycle = true
	var damage := kick_damage if current_melee_kind == MeleeKind.KICK else melee_damage
	var knockback := kick_knockback if current_melee_kind == MeleeKind.KICK else melee_knockback
	if player.has_method("apply_melee_hit"):
		player.apply_melee_hit(damage, global_position.x, knockback, melee_lift)
	elif player.has_method("take_damage"):
		player.take_damage(damage)


func _on_animation_finished() -> void:
	if state == State.FIRE:
		_enter_state(State.RECOVER)


func _play_if_needed(animation_name: StringName) -> void:
	if sprite.animation != animation_name:
		sprite.play(animation_name)


func _should_force_melee() -> bool:
	if state not in [State.IDLE, State.PATROL, State.CHASE, State.KEEP_DISTANCE]:
		return false
	if melee_timer > 0.0:
		return false
	return _is_in_melee_zone()


func _is_in_melee_zone() -> bool:
	return _is_target_in_zone(melee_lock_range, melee_y_tolerance)


func _is_target_in_zone(horizontal_limit: float, vertical_limit: float) -> bool:
	if not _has_target():
		return false

	var horizontal_distance: float = _target_distance_x()
	var vertical_distance: float = abs(target.global_position.y - global_position.y)
	return horizontal_distance <= horizontal_limit and vertical_distance <= vertical_limit


func _create_sprite_frames() -> SpriteFrames:
	var texture := sprite_sheet
	if texture == null:
		texture = load(_default_sprite_sheet_path()) as Texture2D
	var frame_set := _get_frame_set()
	var frames := SpriteFrames.new()
	_add_animation(frames, texture, &"idle", 2.0, true, frame_set["idle"])
	_add_animation(frames, texture, &"walk", 8.0, true, frame_set["walk"])
	_add_animation(frames, texture, &"run", 12.0, true, frame_set["run"])
	_add_animation(frames, texture, &"aim", 8.0, false, frame_set["aim"])
	_add_animation(frames, texture, &"fire", 14.0, false, frame_set["fire"])
	_add_animation(frames, texture, &"point", 4.0, true, frame_set["point"])
	_add_animation(frames, texture, &"punch", 14.0, false, frame_set["punch"])
	_add_animation(frames, texture, &"kick", 12.0, false, frame_set["kick"])
	_add_animation(frames, texture, &"crouch", 6.0, true, frame_set["crouch"])
	_add_animation(frames, texture, &"crouch_aim", 6.0, true, frame_set["crouch_aim"])
	_add_animation(frames, texture, &"crouch_shoot", 12.0, false, frame_set["crouch_shoot"])
	_add_animation(frames, texture, &"hurt", 8.0, false, frame_set["hurt"])
	_add_animation(frames, texture, &"knockdown", 4.0, false, frame_set["knockdown"])
	_add_animation(frames, texture, &"getup", 4.0, false, frame_set["getup"])
	return frames


func _default_sprite_sheet_path() -> String:
	match agent_kind:
		AgentKind.EXECUTOR:
			return "res://art/Enemies/agent4_clean.png"
		AgentKind.GLITCH:
			return "res://art/Enemies/agent6_clean.png"
		_:
			return "res://art/Enemies/agent3_clean.png"


func _get_frame_set() -> Dictionary:
	match agent_kind:
		AgentKind.EXECUTOR:
			return EXECUTOR_FRAMES
		AgentKind.GLITCH:
			return GLITCH_FRAMES
		_:
			return AGENT_FRAMES


func _add_animation(frames: SpriteFrames, texture: Texture2D, animation_name: StringName, speed: float, loops: bool, regions: Array) -> void:
	frames.add_animation(animation_name)
	frames.set_animation_speed(animation_name, speed)
	frames.set_animation_loop(animation_name, loops)

	for region: Rect2 in regions:
		var atlas := AtlasTexture.new()
		atlas.atlas = texture
		atlas.region = region
		frames.add_frame(animation_name, atlas)
