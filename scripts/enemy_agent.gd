extends CharacterBody2D

enum State {
	IDLE,
	PATROL,
	CHASE,
	HOLD_RANGE,
	AIM,
	FIRE,
	RECOVER,
	MELEE,
	HURT,
	DOWN,
}

const AGENT_FRAMES := {
	"idle": [
		Rect2(70, 176, 176, 324),
		Rect2(276, 176, 176, 324),
	],
	"walk": [
		Rect2(484, 184, 196, 316),
		Rect2(692, 184, 196, 316),
		Rect2(904, 184, 196, 316),
	],
	"aim": [
		Rect2(1108, 174, 262, 326),
	],
	"fire": [
		Rect2(1376, 172, 324, 328),
	],
	"melee": [
		Rect2(70, 176, 176, 324),
	],
	"hurt": [
		Rect2(1742, 188, 202, 312),
	],
	"down": [
		Rect2(1940, 204, 214, 296),
	],
}

@export var target_path: NodePath
@export var max_health: int = 90
@export var move_speed: float = 132.0
@export var backstep_speed: float = 96.0
@export var gravity_multiplier: float = 1.65
@export var detect_range: float = 860.0
@export var lose_interest_range: float = 1040.0
@export var ideal_range: float = 430.0
@export var range_tolerance: float = 70.0
@export var too_close_range: float = 520.0
@export var melee_range: float = 300.0
@export var melee_trigger_x: float = 520.0
@export var melee_trigger_y: float = 150.0
@export var close_combat_range: float = 560.0
@export var patrol_distance: float = 260.0
@export var aim_time: float = 0.34
@export var fire_time: float = 0.12
@export var recover_time: float = 0.46
@export var melee_windup_time: float = 0.08
@export var melee_active_time: float = 0.22
@export var melee_recover_time: float = 0.32
@export var melee_lunge_speed: float = 148.0
@export var shoot_cooldown: float = 1.1
@export var melee_cooldown: float = 0.72
@export var melee_damage: int = 10
@export var melee_knockback: float = 420.0
@export var melee_lift: float = -110.0
@export var bullet_damage: int = 13
@export var muzzle_offset := Vector2(88.0, -108.0)

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var hurtbox: Area2D = $Hurtbox
@onready var melee_hitbox: Area2D = $MeleeHitbox

var target: Node2D
var melee_flash: Line2D
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
	_create_melee_flash()
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
		State.HOLD_RANGE:
			_tick_hold_range(delta)
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
	if _should_force_melee():
		_enter_state(State.MELEE)
	elif _can_see_target():
		_enter_state(State.CHASE)
	elif state_time <= 0.0:
		_enter_state(State.PATROL)


func _tick_patrol(delta: float) -> void:
	if _should_force_melee():
		_enter_state(State.MELEE)
		return
	if _can_see_target():
		_enter_state(State.CHASE)
		return

	if abs(global_position.x - patrol_origin.x) >= patrol_distance:
		patrol_direction *= -1.0

	_set_facing(patrol_direction)
	velocity.x = patrol_direction * move_speed * 0.48
	_play_if_needed(&"walk")

	if state_time <= 0.0:
		_enter_state(State.IDLE)


func _tick_chase(delta: float) -> void:
	if not _has_target() or _target_distance_x() > lose_interest_range:
		_enter_state(State.PATROL)
		return

	if _should_force_melee():
		_enter_state(State.MELEE)
		return

	_face_target()
	var distance := _target_distance_x()

	if distance <= too_close_range:
		_enter_state(State.HOLD_RANGE)
	elif distance <= ideal_range + range_tolerance and distance > close_combat_range:
		_enter_state(State.AIM if shoot_timer <= 0.0 else State.HOLD_RANGE)
	else:
		velocity.x = facing * move_speed
		_play_if_needed(&"walk")


func _tick_hold_range(delta: float) -> void:
	if not _has_target():
		_enter_state(State.PATROL)
		return

	if _should_force_melee():
		_enter_state(State.MELEE)
		return

	_face_target()
	var distance := _target_distance_x()

	if distance < too_close_range:
		if melee_timer <= 0.08:
			velocity.x = facing * move_speed * 0.42
			_play_if_needed(&"walk")
		else:
			velocity.x = 0.0
			_play_if_needed(&"idle")
	elif distance > ideal_range + range_tolerance:
		_enter_state(State.CHASE)
	elif shoot_timer <= 0.0 and not _is_target_in_melee_zone(close_combat_range, melee_trigger_y):
		_enter_state(State.AIM)
	else:
		_slow_down(delta)
		_play_if_needed(&"idle")


func _tick_aim(delta: float) -> void:
	if not _has_target():
		_enter_state(State.PATROL)
		return

	if _should_force_melee():
		_enter_state(State.MELEE)
		return
	elif _is_close_combat_distance():
		_enter_state(State.HOLD_RANGE)
		return

	_face_target()
	_slow_down(delta)
	_play_if_needed(&"aim")

	if state_time <= 0.0:
		_enter_state(State.FIRE)


func _tick_fire(delta: float) -> void:
	if _should_force_melee():
		_enter_state(State.MELEE)
		return
	elif _is_close_combat_distance():
		_enter_state(State.HOLD_RANGE)
		return

	_face_target()
	_slow_down(delta)
	_play_if_needed(&"fire")

	if not has_fired_this_cycle:
		has_fired_this_cycle = true
		_shoot()

	if state_time <= 0.0:
		_enter_state(State.RECOVER)


func _tick_recover(delta: float) -> void:
	if _should_force_melee():
		_enter_state(State.MELEE)
		return

	_slow_down(delta)
	_play_if_needed(&"aim")

	if state_time <= 0.0:
		_enter_state(State.HOLD_RANGE if _can_see_target() else State.PATROL)


func _tick_melee(delta: float) -> void:
	_face_target()
	_play_if_needed(&"melee")

	var active_start_time := melee_active_time + melee_recover_time
	var active_end_time := melee_recover_time
	if state_time <= active_start_time and state_time > active_end_time:
		if not melee_is_active:
			melee_is_active = true
			melee_hitbox.monitoring = true
		sprite.position.x = base_sprite_position.x + facing * 18.0
		velocity.x = facing * melee_lunge_speed
		_try_apply_melee_damage()
	else:
		if melee_is_active:
			melee_is_active = false
			melee_hitbox.monitoring = false
			_hide_melee_flash()
		sprite.position.x = move_toward(sprite.position.x, base_sprite_position.x, 160.0 * delta)
		_slow_down(delta)

	if state_time <= 0.0:
		melee_hitbox.monitoring = false
		melee_is_active = false
		_hide_melee_flash()
		sprite.position = base_sprite_position
		_enter_state(State.HOLD_RANGE if _can_see_target() else State.PATROL)


func _tick_hurt(delta: float) -> void:
	velocity.x = move_toward(velocity.x, 0.0, move_speed * delta * 5.0)
	_play_if_needed(&"hurt")
	if state_time <= 0.0:
		_enter_state(State.HOLD_RANGE if _can_see_target() else State.PATROL)


func _enter_state(next_state: State) -> void:
	state = next_state
	has_fired_this_cycle = false
	melee_hitbox.monitoring = false
	melee_is_active = false
	_hide_melee_flash()
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
			_play_if_needed(&"walk")
		State.HOLD_RANGE:
			_play_if_needed(&"idle")
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
			_play_if_needed(&"aim")
		State.MELEE:
			state_time = melee_windup_time + melee_active_time + melee_recover_time
			melee_timer = melee_cooldown
			shoot_timer = max(shoot_timer, melee_cooldown + 0.35)
			has_melee_hit_this_cycle = false
			_update_melee_hitbox_direction()
			velocity.x = 0.0
			_play_if_needed(&"melee")
		State.HURT:
			state_time = 0.28
			velocity.x = -facing * 128.0
			_play_if_needed(&"hurt")
		State.DOWN:
			_die()


func _shoot() -> void:
	if _is_close_combat_distance():
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
	tracer.default_color = Color(1.0, 0.08, 0.06, 1.0)
	bullet.add_child(tracer)

	var glow := Line2D.new()
	glow.name = "Glow"
	glow.points = PackedVector2Array([Vector2(-12, 0), Vector2(12, 0)])
	glow.width = 8.0
	glow.default_color = Color(1.0, 0.55, 0.16, 0.35)
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
	_play_if_needed(&"down")
	await get_tree().create_timer(1.15).timeout
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
	return abs(to_target.x) <= detect_range and abs(to_target.y) <= 180.0


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

	if _is_target_in_melee_zone(560.0, 170.0):
		_apply_melee_hit_to_target(target)


func _apply_melee_hit_to_target(player: Node) -> void:
	if has_melee_hit_this_cycle:
		return

	has_melee_hit_this_cycle = true
	_show_melee_flash()
	if player.has_method("apply_melee_hit"):
		player.apply_melee_hit(melee_damage, global_position.x, melee_knockback, melee_lift)
	elif player.has_method("take_damage"):
		player.take_damage(melee_damage)


func _on_animation_finished() -> void:
	if state == State.FIRE:
		_enter_state(State.RECOVER)


func _play_if_needed(animation_name: StringName) -> void:
	if sprite.animation != animation_name:
		sprite.play(animation_name)


func _should_force_melee() -> bool:
	return state != State.MELEE and state != State.HURT and state != State.DOWN and melee_timer <= 0.0 and _is_target_in_melee_zone(melee_trigger_x, melee_trigger_y)


func _is_close_combat_distance() -> bool:
	return _is_target_in_melee_zone(close_combat_range, melee_trigger_y)


func _is_target_in_melee_zone(horizontal_limit: float, vertical_limit: float) -> bool:
	if not _has_target():
		return false

	var horizontal_distance: float = _target_distance_x()
	var vertical_distance: float = abs(target.global_position.y - global_position.y)
	return horizontal_distance <= horizontal_limit and vertical_distance <= vertical_limit


func _create_melee_flash() -> void:
	melee_flash = Line2D.new()
	melee_flash.name = "MeleeFlash"
	melee_flash.z_index = 30
	melee_flash.width = 4.0
	melee_flash.default_color = Color(1.0, 0.78, 0.18, 0.95)
	melee_flash.points = PackedVector2Array([
		Vector2(68, -112),
		Vector2(92, -100),
		Vector2(116, -112),
	])
	melee_flash.visible = false
	add_child(melee_flash)


func _show_melee_flash() -> void:
	if melee_flash == null:
		return

	melee_flash.scale.x = facing
	melee_flash.visible = true


func _hide_melee_flash() -> void:
	if melee_flash != null:
		melee_flash.visible = false


func _create_sprite_frames() -> SpriteFrames:
	var texture := load("res://art/Enemies/agent3_clean.png") as Texture2D
	var frames := SpriteFrames.new()
	_add_animation(frames, texture, &"idle", 2.0, true, AGENT_FRAMES["idle"])
	_add_animation(frames, texture, &"walk", 7.5, true, AGENT_FRAMES["walk"])
	_add_animation(frames, texture, &"aim", 1.0, true, AGENT_FRAMES["aim"])
	_add_animation(frames, texture, &"fire", 10.0, false, AGENT_FRAMES["fire"])
	_add_animation(frames, texture, &"melee", 10.0, false, AGENT_FRAMES["melee"])
	_add_animation(frames, texture, &"hurt", 8.0, false, AGENT_FRAMES["hurt"])
	_add_animation(frames, texture, &"down", 1.0, false, AGENT_FRAMES["down"])
	return frames


func _add_animation(frames: SpriteFrames, texture: Texture2D, animation_name: StringName, speed: float, loops: bool, regions: Array) -> void:
	frames.add_animation(animation_name)
	frames.set_animation_speed(animation_name, speed)
	frames.set_animation_loop(animation_name, loops)

	for region: Rect2 in regions:
		var atlas := AtlasTexture.new()
		atlas.atlas = texture
		atlas.region = region
		frames.add_frame(animation_name, atlas)
