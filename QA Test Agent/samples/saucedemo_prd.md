# Product Requirements Document
## SauceDemo E-Commerce Web Application

**Application URL:** https://www.saucedemo.com
**Document version:** 1.0
**Owner:** QA Engineering
**Status:** Approved for testing

---

## 1. Overview

SauceDemo is a web-based e-commerce storefront that lets an authenticated
user browse a catalog of products, manage a shopping cart, and complete a
checkout flow. This document describes the functional requirements the
autonomous test agent should validate.

Known test accounts (public demo credentials, not secrets):

| Username | Password | Notes |
|---|---|---|
| standard_user | secret_sauce | Normal user, full access |
| locked_out_user | secret_sauce | Account is locked; login must fail with an error |
| problem_user | secret_sauce | Login succeeds; UI has known display defects |
| performance_glitch_user | secret_sauce | Login succeeds but is slow |

---

## 2. Roles

- **Guest** — unauthenticated visitor, can only see the login page.
- **Authenticated Shopper** — logged-in user, can browse, add to cart, and
  check out.

---

## 3. Functional Requirements

### REQ-001: User Login (valid credentials)
**Priority:** HIGH
**Description:** A user with valid credentials (username `standard_user`,
password `secret_sauce`) can log in and is redirected to the Products page.
**Acceptance Criteria:**
- Login form accepts a username and a password.
- Submitting valid credentials navigates to the inventory/products page.
- The products page displays a non-empty list of products.
**Preconditions:** User is on the login page, not already authenticated.

### REQ-002: User Login (invalid credentials)
**Priority:** HIGH
**Description:** A user with an incorrect username or password must not be
logged in, and must see a clear error message.
**Acceptance Criteria:**
- Submitting an unknown username or wrong password keeps the user on the
  login page.
- An error message is displayed indicating the login failed.
**Negative scenario:** Login with a valid username and a deliberately wrong
password must fail the same way.

### REQ-003: Locked-out account is rejected
**Priority:** HIGH
**Description:** The `locked_out_user` account must never be allowed to log
in, even with the correct password, and must see an explicit "locked out"
error message.
**Acceptance Criteria:**
- Login attempt with `locked_out_user` / `secret_sauce` fails.
- The displayed error explicitly mentions the user has been locked out.

### REQ-004: Product catalog is browsable
**Priority:** HIGH
**Description:** After login, the user can see all available products with
a name, a price, and an "Add to cart" action for each.
**Acceptance Criteria:**
- Each product listed shows a name and a price.
- Each product has a visible control to add it to the cart.

### REQ-005: Sort products
**Priority:** MEDIUM
**Description:** The user can reorder the product list by name (A-Z, Z-A)
and by price (low-high, high-low) using a sort control.
**Acceptance Criteria:**
- Selecting "Price (low to high)" reorders the visible products so prices
  are non-decreasing top to bottom.
- Selecting "Name (Z to A)" reorders the visible products in reverse
  alphabetical order.

### REQ-006: Add product to cart
**Priority:** HIGH
**Description:** Clicking "Add to cart" on a product adds exactly one unit
of that product to the cart and updates the cart icon's item count.
**Acceptance Criteria:**
- After adding one product, the cart badge shows a count of 1.
- The button for that product changes to a "Remove" action.
**Dependencies:** REQ-001 (must be logged in).

### REQ-007: Remove product from cart
**Priority:** MEDIUM
**Description:** A product already in the cart can be removed, either from
the product list or from the cart page, and the cart count decreases
accordingly.
**Acceptance Criteria:**
- Removing the only item in the cart returns the cart badge to empty/zero.
**Dependencies:** REQ-006.

### REQ-008: View cart contents
**Priority:** HIGH
**Description:** The cart page lists every product the user has added,
with correct name, quantity, and price for each line item.
**Acceptance Criteria:**
- Every product added via REQ-006 appears on the cart page.
- The cart page offers a way to proceed to checkout and a way to continue
  shopping.
**Dependencies:** REQ-006.

### REQ-009: Checkout - customer information
**Priority:** HIGH
**Description:** Starting checkout prompts the user for first name, last
name, and zip/postal code before continuing.
**Acceptance Criteria:**
- Submitting the form without all three fields shows a validation error and
  does not proceed.
- Submitting all three fields proceeds to the order overview step.
**Negative scenario:** Submitting the checkout information form with any one
of the three fields left blank must be rejected with an error message.
**Dependencies:** REQ-008.

### REQ-010: Checkout - order overview and totals
**Priority:** HIGH
**Description:** Before finishing checkout, the user sees an order summary
listing each item, the item total, tax, and the final total.
**Acceptance Criteria:**
- The summary lists every item that was in the cart.
- A total price is displayed and is greater than zero when the cart is
  non-empty.
**Dependencies:** REQ-009.

### REQ-011: Complete checkout
**Priority:** HIGH
**Description:** Finishing checkout from the order overview shows a
confirmation page acknowledging the order, and empties the cart.
**Acceptance Criteria:**
- A completion/confirmation message is shown after finishing checkout.
- Returning to the products page shows the cart badge as empty.
**Dependencies:** REQ-010.

### REQ-012: Logout
**Priority:** MEDIUM
**Description:** An authenticated user can log out from the main menu and
is returned to the login page.
**Acceptance Criteria:**
- After logout, the login form is shown again.
- Attempting to revisit the products page without logging back in does not
  show product data.
**Dependencies:** REQ-001.

---

## 4. Out of Scope

- Payment processing is simulated only; no real payment gateway exists and
  must not be tested as if one does.
- Account creation / registration is not supported by this application and
  should not be tested.
- Password reset is not supported by this application and should not be
  tested.

## 5. Business Rules

- A user must be authenticated to access any page other than the login
  page; direct navigation to an internal page while logged out must not
  reveal protected data.
- The cart badge count must always equal the number of distinct products
  currently in the cart.
- Prices shown in the cart and checkout summary must match the prices shown
  in the product catalog.
