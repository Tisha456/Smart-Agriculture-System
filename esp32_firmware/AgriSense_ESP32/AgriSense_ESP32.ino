#include <Servo.h>

// Motor Direction Pins
const int IN1 = 2;   // Left Direction 1
const int IN2 = 3;   // Left Direction 2
const int IN3 = 4;   // Right Direction 1
const int IN4 = 5;   // Right Direction 2

// Servo Pin
const int SERVO_PIN = 8;

// Ultrasonic Sensor Pins
const int TRIG_PIN = 9;
const int ECHO_PIN = 10;

Servo myServo;

// Obstacle threshold distance in centimeters
const int OBSTACLE_LIMIT = 20;

void setup() {
  // Set motor control pins as outputs
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  // Set ultrasonic sensor pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Initialize servo motor to center position
  myServo.attach(SERVO_PIN);
  myServo.write(90);
  delay(1000);
}

void loop() {
  int distance = getDistance();

  if (distance <= OBSTACLE_LIMIT) {
    stopMotors();
    delay(200);

    // Back up slightly before scanning
    moveBackward();
    delay(300);
    stopMotors();
    delay(200);

    // Scan surroundings
    int distanceRight = lookRight();
    delay(200);
    int distanceLeft = lookLeft();
    delay(200);

    // Turn toward the clearest path
    if (distanceRight >= distanceLeft) {
      turnRight();
      delay(400); 
    } else {
      turnLeft();
      delay(400); 
    }
    stopMotors();
  } else {
    moveForward();
  }

  delay(50);
}

// Distance measurement function
int getDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms timeout
  if (duration == 0) return 400; // Return max distance if no bounce back

  return duration * 0.034 / 2;
}

// Servo scanning helpers
int lookRight() {
  myServo.write(20);
  delay(500);
  int dist = getDistance();
  myServo.write(90);
  return dist;
}

int lookLeft() {
  myServo.write(160);
  delay(500);
  int dist = getDistance();
  myServo.write(90);
  return dist;
}

// Movement control functions
void moveForward() {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void moveBackward() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void turnRight() {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void turnLeft() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void stopMotors() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
}