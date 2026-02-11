import { users, type User, type UpsertUser } from "@shared/models/auth";
import { db } from "../../db";
import { eq, ne } from "drizzle-orm";

// Admin email - only this user can access admin panel
const ADMIN_EMAIL = "ssukduang@gmail.com";

// Interface for auth storage operations
// (IMPORTANT) These user operations are mandatory for Replit Auth.
export interface IAuthStorage {
  getUser(id: string): Promise<User | undefined>;
  upsertUser(user: UpsertUser): Promise<User>;
  getAllUsers(): Promise<User[]>;
  updateUserApproval(userId: string, status: "approved" | "rejected"): Promise<User | undefined>;
  acceptPolicy(userId: string): Promise<User | undefined>;
}

class AuthStorage implements IAuthStorage {
  async getUser(id: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async upsertUser(userData: UpsertUser): Promise<User> {
    const userId = userData.id;
    if (!userId) {
      throw new Error("Missing user id in upsert payload");
    }

    // Check if this is the admin email - auto-approve and set admin flag
    const isAdmin = userData.email?.toLowerCase() === ADMIN_EMAIL.toLowerCase();
    
    // First check if a user with this ID already exists
    const existingById = await this.getUser(userId);
    
    if (existingById) {
      // Update existing user by ID
      const [user] = await db
        .update(users)
        .set({
          ...userData,
          updatedAt: new Date(),
          // If it's the admin, ensure they stay admin and approved
          ...(isAdmin ? { isAdmin: true, approvalStatus: "approved" } : {}),
        })
        .where(eq(users.id, userId))
        .returning();
      return user;
    }
    
    // Check if email already exists (different ID but same email)
    if (userData.email) {
      const [existingByEmail] = await db.select().from(users).where(eq(users.email, userData.email));
      if (existingByEmail) {
        // Update the existing user's ID to the new one (Replit Auth may regenerate sub IDs)
        const [user] = await db
          .update(users)
          .set({
            id: userId,
            firstName: userData.firstName,
            lastName: userData.lastName,
            profileImageUrl: userData.profileImageUrl,
            updatedAt: new Date(),
            ...(isAdmin ? { isAdmin: true, approvalStatus: "approved" } : {}),
          })
          .where(eq(users.id, existingByEmail.id))
          .returning();
        return user;
      }
    }
    
    // Insert new user
    const [user] = await db
      .insert(users)
      .values({
        ...userData,
        isAdmin: isAdmin,
        approvalStatus: isAdmin ? "approved" : "pending",
      })
      .returning();
    return user;
  }

  async getAllUsers(): Promise<User[]> {
    return db.select().from(users).orderBy(users.createdAt);
  }

  async updateUserApproval(userId: string, status: "approved" | "rejected"): Promise<User | undefined> {
    const [user] = await db
      .update(users)
      .set({ approvalStatus: status, updatedAt: new Date() })
      .where(eq(users.id, userId))
      .returning();
    return user;
  }

  async acceptPolicy(userId: string): Promise<User | undefined> {
    const [user] = await db
      .update(users)
      .set({ policyAcceptedAt: new Date(), updatedAt: new Date() })
      .where(eq(users.id, userId))
      .returning();
    return user;
  }
}

export const authStorage = new AuthStorage();
