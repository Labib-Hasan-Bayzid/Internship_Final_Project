from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
Ecosystem = Literal["python","node"]

class ProjectCreate(BaseModel):
    name: str = Field(min_length=2,max_length=120)
    repository: str|None = None
    default_ecosystem: Ecosystem = "python"
class ProjectUpdate(BaseModel):
    name: str|None=None; repository: str|None=None; default_ecosystem:Ecosystem|None=None; active:bool|None=None
    auto_verify_pull_requests:bool|None=None; github_installation_id:int|None=None; review_network_additions:bool|None=None
    review_process_additions:bool|None=None; max_file_delta:int|None=Field(default=None,ge=0,le=1000); block_on_test_failure:bool|None=None
    runtime_regression_review_percent:int|None=Field(default=None,ge=0,le=1000); runtime_regression_block_percent:int|None=Field(default=None,ge=0,le=5000)
    runtime_regression_min_ms:int|None=Field(default=None,ge=0,le=600000)
class ProjectOut(ProjectCreate):
    id:str; organization_id:str; active:bool; auto_verify_pull_requests:bool; github_installation_id:int|None
    review_network_additions:bool; review_process_additions:bool; max_file_delta:int; block_on_test_failure:bool
    runtime_regression_review_percent:int; runtime_regression_block_percent:int; runtime_regression_min_ms:int
    created_at:datetime; updated_at:datetime
    model_config=ConfigDict(from_attributes=True)
class VerificationCreate(BaseModel):
    package_name:str=Field(min_length=1,max_length=200); ecosystem:Ecosystem; old_version:str=Field(min_length=1,max_length=100); new_version:str=Field(min_length=1,max_length=100)
    project_id:str|None=None; smoke_import:str|None=Field(default=None,max_length=200,pattern=r"^[A-Za-z0-9_./,@-]+$")

    @model_validator(mode="after")
    def versions_must_change(self):
        if self.old_version.strip() == self.new_version.strip():
            raise ValueError("old_version and new_version must be different")
        return self
class VerificationOut(BaseModel):
    id:str; organization_id:str; project_id:str; package_name:str; ecosystem:str; old_version:str; new_version:str; smoke_import:str|None
    status:str; decision:str|None; severity:str|None; summary:str|None; result_json:dict[str,Any]|None; verification_key:str|None; ai_explanation:str|None; ai_status:str; ai_attempts:int; ai_error:str|None
    source:str; github_repo:str|None; github_pr:int|None; github_sha:str|None; github_check_run_id:int|None; github_published_at:datetime|None; github_comment_id:int|None; manifest_path:str|None
    k8s_job_name:str|None; error_message:str|None; created_at:datetime; started_at:datetime|None; finished_at:datetime|None; updated_at:datetime
    model_config=ConfigDict(from_attributes=True)
class ExplainOut(BaseModel): explanation:str
class StatsOut(BaseModel): total:int; pass_count:int; review_count:int; block_count:int; running_count:int
class IntegrationOut(BaseModel): kubernetes:bool; ai_enabled:bool; ai_configured:bool; ai_model:str; github_configured:bool; github_app_url:str|None; github_webhook_url:str|None; github_check_name:str; stripe_configured:bool
class CheckoutIn(BaseModel): plan:Literal["TEAM","BUSINESS"]
class BillingOut(BaseModel):
    organization_id:str; plan_code:str; subscription_status:str; stripe_customer_id:str|None; stripe_subscription_id:str|None; cancel_at_period_end:bool; current_period_end:datetime|None; usage:dict[str,int]; limits:dict[str,int]
class OrganizationOut(BaseModel): id:str; name:str; slug:str; status:str; plan_code:str; billing_email:str|None; created_at:datetime; updated_at:datetime
class OrganizationCreate(BaseModel):
    name:str=Field(min_length=2,max_length=160)
    slug:str=Field(min_length=2,max_length=100,pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
class OrganizationUpdate(BaseModel): name:str=Field(min_length=2,max_length=160); billing_email:str|None=None
class MemberOut(BaseModel): membership_id:str; user_id:str; email:str; name:str; role:str; status:str; created_at:datetime
class MemberRoleUpdate(BaseModel): role:Literal["OWNER","ADMIN","MEMBER","VIEWER"]; status:Literal["ACTIVE","SUSPENDED"]
class InviteCreate(BaseModel): email:str; role:Literal["ADMIN","MEMBER","VIEWER"]="MEMBER"
class InviteOut(BaseModel): id:str; email:str; role:str; status:str; expires_at:datetime; invite_url:str
class UsageOut(BaseModel): plan_code:str; limits:dict[str,int]; verification_runs:int; ai_explanations:int; projects:int; period_start:datetime
