from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    ROLES = [
        ('job_seeker', 'Job Seeker'),
        ('hr', 'HR/Recruiter'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='user_profile')
    role = models.CharField(max_length=20, choices=ROLES, default='job_seeker')

    def __str__(self):
        return f"{self.user.username} - {self.role}"

class HRProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='hr_profile')
    company_name = models.CharField(max_length=255, blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True)
    logo = models.ImageField(upload_to='company_logos/', blank=True, null=True)

    def __str__(self):
        return self.company_name or self.user.username

class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Job(models.Model):
    title = models.CharField(max_length=255)
    recruiter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posted_jobs', null=True, blank=True)
    company = models.CharField(max_length=255, default="Local Corp")
    description = models.TextField()
    required_skills = models.ManyToManyField(Skill, related_name='jobs')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class CandidateProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    full_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    skills = models.ManyToManyField(Skill, related_name='candidates')
    experience = models.JSONField(default=list, blank=True)
    education = models.JSONField(default=list, blank=True)
    ai_polished_summary = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.full_name or self.user.username

class Resume(models.Model):
    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name='resumes')
    file = models.FileField(upload_to='resumes/')
    raw_text = models.TextField(blank=True, null=True)
    structured_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Resume for {self.candidate.full_name}"

class JobApplication(models.Model):
    STATUS_CHOICES = [
        ('Applied', 'Applied'),
        ('Shortlisted', 'Shortlisted'),
        ('Rejected', 'Rejected'),
    ]
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='applications')
    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name='applications')
    resume = models.ForeignKey(Resume, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Applied')
    applied_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.candidate.full_name} - {self.job.title}"

class MatchScore(models.Model):
    application = models.OneToOneField(JobApplication, on_delete=models.CASCADE, related_name='match_score')
    score = models.FloatField()
    explanation = models.TextField(blank=True, null=True)
    missing_skills = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"Score: {self.score} for {self.application}"

