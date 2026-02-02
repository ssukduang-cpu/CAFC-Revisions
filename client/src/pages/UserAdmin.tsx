import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ArrowLeft, CheckCircle, XCircle, Clock, Users, Shield, RefreshCw } from "lucide-react";
import { Link } from "wouter";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/use-auth";
import type { User } from "@shared/models/auth";

export default function UserAdmin() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { user: currentUser, isLoading: authLoading } = useAuth();

  const { data: users, isLoading, refetch } = useQuery<User[]>({
    queryKey: ["/api/admin/users"],
    queryFn: async () => {
      const res = await fetch("/api/admin/users", { credentials: "include" });
      if (res.status === 403) {
        throw new Error("Access denied. Admin privileges required.");
      }
      if (!res.ok) throw new Error("Failed to fetch users");
      return res.json();
    },
    retry: false,
  });

  const approvalMutation = useMutation({
    mutationFn: async ({ userId, status }: { userId: string; status: "approved" | "rejected" }) => {
      const res = await fetch(`/api/admin/users/${userId}/approval`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status }),
      });
      if (!res.ok) throw new Error("Failed to update user");
      return res.json();
    },
    onSuccess: (_, { status }) => {
      queryClient.invalidateQueries({ queryKey: ["/api/admin/users"] });
      toast({
        title: "User Updated",
        description: `User has been ${status}.`,
      });
    },
    onError: (error) => {
      toast({
        title: "Error",
        description: error.message,
        variant: "destructive",
      });
    },
  });

  if (authLoading || isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!currentUser?.isAdmin) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <Card className="max-w-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-600">
              <Shield className="h-5 w-5" />
              Access Denied
            </CardTitle>
            <CardDescription>
              You don't have permission to access this page. Only administrators can manage users.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/">
              <Button data-testid="go-home-button">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Go Home
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  const pendingUsers = users?.filter(u => u.approvalStatus === "pending") || [];
  const approvedUsers = users?.filter(u => u.approvalStatus === "approved") || [];
  const rejectedUsers = users?.filter(u => u.approvalStatus === "rejected") || [];

  const UserCard = ({ user }: { user: User }) => (
    <div className="flex items-center justify-between p-4 border rounded-lg bg-card" data-testid={`user-card-${user.id}`}>
      <div className="flex items-center gap-3">
        {user.profileImageUrl ? (
          <img src={user.profileImageUrl} alt="" className="h-10 w-10 rounded-full" />
        ) : (
          <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center">
            <Users className="h-5 w-5 text-muted-foreground" />
          </div>
        )}
        <div>
          <p className="font-medium">
            {user.firstName} {user.lastName}
            {user.isAdmin && (
              <Badge variant="secondary" className="ml-2">Admin</Badge>
            )}
          </p>
          <p className="text-sm text-muted-foreground">{user.email || "No email"}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {user.policyAcceptedAt && (
          <Badge variant="outline" className="text-green-600">
            <CheckCircle className="h-3 w-3 mr-1" />
            Policy Accepted
          </Badge>
        )}
        {!user.isAdmin && (
          <>
            {user.approvalStatus === "pending" && (
              <>
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => approvalMutation.mutate({ userId: user.id, status: "approved" })}
                  disabled={approvalMutation.isPending}
                  data-testid={`approve-button-${user.id}`}
                >
                  <CheckCircle className="h-4 w-4 mr-1" />
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => approvalMutation.mutate({ userId: user.id, status: "rejected" })}
                  disabled={approvalMutation.isPending}
                  data-testid={`reject-button-${user.id}`}
                >
                  <XCircle className="h-4 w-4 mr-1" />
                  Reject
                </Button>
              </>
            )}
            {user.approvalStatus === "approved" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => approvalMutation.mutate({ userId: user.id, status: "rejected" })}
                disabled={approvalMutation.isPending}
                data-testid={`revoke-button-${user.id}`}
              >
                <XCircle className="h-4 w-4 mr-1" />
                Revoke
              </Button>
            )}
            {user.approvalStatus === "rejected" && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => approvalMutation.mutate({ userId: user.id, status: "approved" })}
                disabled={approvalMutation.isPending}
                data-testid={`restore-button-${user.id}`}
              >
                <CheckCircle className="h-4 w-4 mr-1" />
                Restore
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-background p-6" data-testid="user-admin-page">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/">
              <Button variant="ghost" size="icon" data-testid="back-button">
                <ArrowLeft className="h-5 w-5" />
              </Button>
            </Link>
            <div>
              <h1 className="text-2xl font-bold">User Management</h1>
              <p className="text-muted-foreground">Approve or reject user access requests</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Link href="/admin">
              <Button variant="outline" data-testid="ingestion-admin-link">
                Ingestion Admin
              </Button>
            </Link>
            <Button variant="outline" onClick={() => refetch()} data-testid="refresh-users">
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Pending Approval</CardDescription>
              <CardTitle className="text-3xl text-yellow-600" data-testid="stat-pending">
                {pendingUsers.length}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <Clock className="h-4 w-4 mr-1" />
                Awaiting review
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Approved Users</CardDescription>
              <CardTitle className="text-3xl text-green-600" data-testid="stat-approved">
                {approvedUsers.length}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <CheckCircle className="h-4 w-4 mr-1" />
                Active access
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Rejected Users</CardDescription>
              <CardTitle className="text-3xl text-red-600" data-testid="stat-rejected">
                {rejectedUsers.length}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center text-muted-foreground">
                <XCircle className="h-4 w-4 mr-1" />
                Access denied
              </div>
            </CardContent>
          </Card>
        </div>

        {pendingUsers.length > 0 && (
          <Card className="border-yellow-200 dark:border-yellow-800">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-yellow-600" />
                Pending Requests ({pendingUsers.length})
              </CardTitle>
              <CardDescription>Users waiting for approval</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {pendingUsers.map(user => (
                  <UserCard key={user.id} user={user} />
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle className="h-5 w-5 text-green-600" />
              Approved Users ({approvedUsers.length})
            </CardTitle>
            <CardDescription>Users with active access</CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="max-h-[400px]">
              <div className="space-y-3">
                {approvedUsers.map(user => (
                  <UserCard key={user.id} user={user} />
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        {rejectedUsers.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <XCircle className="h-5 w-5 text-red-600" />
                Rejected Users ({rejectedUsers.length})
              </CardTitle>
              <CardDescription>Users with denied access</CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="max-h-[300px]">
                <div className="space-y-3">
                  {rejectedUsers.map(user => (
                    <UserCard key={user.id} user={user} />
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
