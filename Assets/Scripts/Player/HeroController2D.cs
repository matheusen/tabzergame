using UnityEngine;

namespace TabzerGame.Player
{
    [RequireComponent(typeof(Rigidbody2D))]
    [RequireComponent(typeof(Collider2D))]
    public sealed class HeroController2D : MonoBehaviour
    {
        [Header("Movement")]
        [SerializeField] private float runSpeed = 7f;
        [SerializeField] private float jumpImpulse = 12f;

        [Header("Ground Check")]
        [SerializeField] private LayerMask groundMask = ~0;
        [SerializeField] private Vector2 groundCheckSize = new(0.8f, 0.08f);
        [SerializeField] private Vector2 groundCheckOffset = new(0f, -0.68f);

        private Rigidbody2D body;
        private float horizontal;
        private bool jumpQueued;

        public bool IsFacingRight { get; private set; } = true;

        private void Awake()
        {
            body = GetComponent<Rigidbody2D>();
            body.freezeRotation = true;
        }

        private void Update()
        {
            bool moveLeft = Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow);
            bool moveRight = Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow);
            horizontal = moveRight ? 1f : moveLeft ? -1f : 0f;

            if (Input.GetKeyDown(KeyCode.Space) || Input.GetKeyDown(KeyCode.W) || Input.GetKeyDown(KeyCode.UpArrow))
            {
                jumpQueued = true;
            }

            if (horizontal > 0.01f)
            {
                Face(true);
            }
            else if (horizontal < -0.01f)
            {
                Face(false);
            }
        }

        private void FixedUpdate()
        {
            body.velocity = new Vector2(horizontal * runSpeed, body.velocity.y);

            if (jumpQueued && IsGrounded())
            {
                body.velocity = new Vector2(body.velocity.x, jumpImpulse);
            }

            jumpQueued = false;
        }

        private bool IsGrounded()
        {
            Vector2 origin = (Vector2)transform.position + groundCheckOffset;
            return Physics2D.OverlapBox(origin, groundCheckSize, 0f, groundMask) != null;
        }

        private void Face(bool right)
        {
            IsFacingRight = right;
            Vector3 scale = transform.localScale;
            scale.x = Mathf.Abs(scale.x) * (right ? 1f : -1f);
            transform.localScale = scale;
        }

        private void OnDrawGizmosSelected()
        {
            Gizmos.color = Color.yellow;
            Gizmos.DrawWireCube((Vector2)transform.position + groundCheckOffset, groundCheckSize);
        }
    }
}
